# This file is part of the traffic assignment code base developed at KU Leuven.
#  Copyright (c) 2020 Paul Ortmann
#  License: GNU GENERAL PUBLIC LICENSE Version 3, 29 June 2007, see license.txt
#  More information at: https://gitlab.kuleuven.be/ITSCreaLab
#  or contact: ITScrealab@kuleuven.be
#
#
from scipy.spatial import cKDTree
from numba.typed import List, Dict
import pandas as pd
import numpy as np
from dtapy.core.jitclasses import SimulationTime, StaticDemand, DynamicDemand
from datastructures.csr import csr_prep, F32CSRMatrix
import osmnx as ox
from osmnx.distance import great_circle_vec
import geopandas as gpd
from shapely.geometry import Point
from geojson import Feature, FeatureCollection, dumps
import networkx as nx
import geojson
from shapely.geometry import LineString
from collections import deque
from json import loads
import itertools


def generate_od_xy(tot_ods, name: str, max_flow=2000, seed=0):
    """

    Parameters
    ----------
    seed : numpy random seed
    tot_ods :total number of OD pairs to be generated
    name : str, name of the city or region to geocode and sample from
    max_flow : maximum demand that is generated

    Returns
    -------
    geojson containing lineStrings and flows
    """
    # 4326 : WGS84
    # 3857 : web mercator
    np.random.seed(seed)
    my_gdf: gpd.geodataframe.GeoDataFrame = ox.geocode_to_gdf(name)
    tot_points = 20 * tot_ods  # could be improved by using the area ratio between bbox and polygon for scaling
    X = np.random.random(tot_points) * (my_gdf.bbox_east[0] - my_gdf.bbox_west[0]) + my_gdf.bbox_west[0]
    # np.normal.normal means uniform distribution between 0 and 1, can easily be replaced (gumbel, gaussian..)
    Y = np.random.random(tot_points) * (my_gdf.bbox_north[0] - my_gdf.bbox_south[0]) + my_gdf.bbox_south[0]
    points = [Point(x, y) for x, y in zip(X, Y)]
    my_points = gpd.geoseries.GeoSeries(points, crs=4326)
    valid_points = my_points[my_points.within(my_gdf.loc[0, 'geometry'])]  # bounding box typically doesn't align
    # with polygon extend so we ought to check which points are inside
    X = np.array(valid_points.geometry.x[:tot_ods * 2])
    Y = np.array(valid_points.geometry.y[:tot_ods * 2])
    destinations = [(x, y) for x, y in zip(X[:tot_ods], Y[:tot_ods])]
    origins = [(x, y) for x, y in zip(X[tot_ods:], Y[tot_ods:])]
    vals = np.random.random(tot_ods) * max_flow
    line_strings = [LineString([[origin[0], origin[1]], [destination[0], destination[1]]]) for origin, destination in
                    zip(origins, destinations)]
    tmp = [{'flow': f} for f in vals]
    my_features = [Feature(geometry=my_linestring, properties=my_tmp) for my_linestring, my_tmp in
                   zip(line_strings, tmp)]
    fc = FeatureCollection(my_features)
    return dumps(fc)


def _check_centroid_connectivity(g: nx.DiGraph):
    """
    verifies if each centroid has at least one connector
    Parameters
    ----------
    g : nx.Digraph

    Returns
    -------

    """
    centroids = [u for u, data_dict in g.nodes(data=True) if 'centroid' in data_dict]
    tot_out_c = [__count_iter_items(g.successors(n)) for n in centroids]
    tot_in_c = [__count_iter_items(g.predecessors(n)) for n in centroids]
    if min(tot_out_c) == 0:
        disconnected_centroids = [i for i, val in enumerate(tot_out_c) if val == 0]
        raise ValueError(f'these centroids do not have an outgoing connector: {disconnected_centroids}')
    if min(tot_in_c) == 0:
        disconnected_centroids = [i for i, val in enumerate(tot_in_c) if val == 0]
        raise ValueError(f'these centroids do not have an incoming connector: {disconnected_centroids}')


def __create_centroid_grid(name: str, spacing=1000):
    """
    creates centroids on a grid that overlap with the polygon that is associated with city or region specified
    under 'name'
    Parameters
    ----------
    name : name of the city to be used as reference polygon
    spacing : distance between two adjacent centroids on the grid

    Returns
    -------

    """
    my_gdf = ox.geocode_to_gdf(name)
    range_ns_meters = great_circle_vec(my_gdf.bbox_north[0], my_gdf.bbox_east[0], my_gdf.bbox_south[0],
                                       my_gdf.bbox_east[0])
    range_ew_meters = great_circle_vec(my_gdf.bbox_east[0], my_gdf.bbox_south[0], my_gdf.bbox_west[0],
                                       my_gdf.bbox_south[0])
    ns_tics = np.linspace(my_gdf.bbox_south[0], my_gdf.bbox_north[0], np.int(np.floor(range_ns_meters / spacing)))
    ew_tics = np.linspace(my_gdf.bbox_west[0], my_gdf.bbox_east[0], np.int(np.floor(range_ew_meters / spacing)))
    grid = np.meshgrid(ew_tics, ns_tics)
    X = grid[0].flatten()
    Y = grid[1].flatten()
    points = [Point(x, y) for x, y in zip(X, Y)]
    points = gpd.geoseries.GeoSeries(points, crs=4326)
    centroids = points[points.within(my_gdf.loc[0, 'geometry'])]
    return centroids


def add_centroids_from_grid(name: str, g, D=2000, k=3):
    """
    partitions the polygon associated with the region/city into squares (with D as the side length in meters)
    and adds one centroid and k connectors to the k nearest nodes for each square.
    Parameters
    ----------
    k : number of connectors to be added per centroid
    g : nx.Digraph for name generated by osmnx
    D : side length of squares
    name : name of the city to which g corresponds
    geojson : geojson string, containing Points which are either origins or destinations.

    Returns
    -------

    """
    if len([u for u, data_dict in g.nodes(data=True) if 'centroid' in data_dict]) > 0:
        raise ValueError('grid generation assumes that no centroids are present in the graph')
    u0 = max(g.nodes) + 1
    centroids = __create_centroid_grid(name, D)
    new_centroids = [(u, {'x': p[0], 'y': p[1], 'centroid': True, 'centroid_id': c}) for u, p, c in
                     zip(range(u0, u0 + len(centroids)), centroids, range(len(centroids)))]
    for u, data in new_centroids:
        g.add_node(u, **data)
        tmp: nx.DiGraph = g
        og_nodes = list(g.nodes)
        for _ in range(k):
            v, length = ox.get_nearest_node(tmp, (data['y'], data['x']), return_dist=True)
            og_nodes.remove(v)
            tmp = tmp.subgraph(og_nodes)
            connector_data = {'connector': True, 'length': length}
            g.add_edge(u, v, **connector_data)
            g.add_edge(v, u, **connector_data)


def parse_demand(data: str, g: nx.DiGraph, time=0):
    """
    Maps travel demand to existing closest centroids in g.
    The demand pattern is added in the graph as its own directed graph and can be retrieved via g.graph['od_graph'],
    it contains edges with a 'weight' entry that indicates the movements from centroid to centroid.
    The corresponding OD tables can be retrieved through calling .to_scipy_sparse_matrix() on the graphs.

    Parameters
    ----------
    time : time stamp for the demand data in seconds, can be used as UNIX epoch to specify dates.
    data : geojson that contains lineStrings (WGS84) as features, each line has an associated
    'flow' stored in the properties dict
    g : networkx DiGraph for the city under consideration with centroids

    There's no checking on whether the data and the nx.Digraph correspond to the same geo-coded region.
    Returns
    -------


    """
    centroid_subgraph = g.subgraph(nodes=[u for u, data_dict in g.nodes(data=True) if 'centroid' in data_dict])
    if centroid_subgraph.number_of_nodes() == 0:
        raise ValueError('Graph does not contain any centroids.')
    data = geojson.loads(data)
    gdf = gpd.GeoDataFrame.from_features(data['features'])
    X0 = [gdf.geometry[u].xy[0][0] for u in range(len(gdf))]
    X1 = [gdf.geometry[u].xy[0][1] for u in range(len(gdf))]
    Y0 = [gdf.geometry[u].xy[1][0] for u in range(len(gdf))]
    Y1 = [gdf.geometry[u].xy[1][1] for u in range(len(gdf))]
    X = np.concatenate((X0, X1))
    Y = np.concatenate((Y0, Y1))
    snapped_centroids, _ = find_nearest_centroids(X,
                                                  Y,
                                                  centroid_subgraph)  # snapped centroids are in nx node id space,
    # and not their respective internal centroid ids
    tot_ods = len(X1)
    new_centroid_ids = np.array([centroid_subgraph.nodes[u]['centroid_id'] for u in snapped_centroids], dtype=np.uint32)
    flows = np.array(gdf['flow'])
    od_graph = nx.DiGraph()
    od_graph.add_nodes_from(
        [(data['centroid_id'], {'nx_id': u}) for u, data in g.nodes(data=True) if 'centroid' in data])
    O, D = np.array_split(new_centroid_ids, 2)
    od_edges = [(i, j, {'weight': flow}) for i, j, flow in zip(O, D, flows)]
    od_graph.add_edges_from(od_edges)
    od_graph.graph['time'] = time
    if 'od_graph' in g.graph:
        g.graph['od_graph'].append(od_graph)
    else:
        g.graph['od_graph'] = [od_graph]


def _build_demand(demand_data, insertion_time, simulation_time: SimulationTime):
    """
    
    Parameters
    ----------
    simulation_time : time object, see class def
    demand_data : List <scipy.lil_matrix> origins x destinations,
     matrix k corresponds to the demand inserted at time[k]
    insertion_time : Array, times at which the demand is loaded

    Returns
    -------

    """

    if not np.all(insertion_time[1:] - insertion_time[:-1] > simulation_time.step_size):
        raise ValueError('insertion times are assumed to be monotonously increasing. The minimum difference between '
                         'two '
                         'insertions is the internal simulation time step')
    time = np.arange(simulation_time.start, simulation_time.end, simulation_time.step_size)
    loading_time_steps = [(np.abs(insertion_time - time)).argmin() for insertion_time in time]
    static_demands = List()
    rows = [np.asarray(lil_demand.nonzero()[0], dtype=np.uint32) for lil_demand in demand_data]
    row_sizes = np.array([lil_demand.nonzero()[0].size for lil_demand in demand_data], dtype=np.uint32)
    cols = [np.asarray(lil_demand.nonzero()[1], dtype=np.uint32) for lil_demand in demand_data]
    col_sizes = np.array([lil_demand.nonzero()[1].size for lil_demand in demand_data], dtype=np.uint32)
    all_destinations, cols = np.unique(np.concatenate(cols), return_inverse=True)
    all_origins, rows = np.unique(np.concatenate(rows), return_inverse=True)
    cols = np.array_split(cols, np.cumsum(col_sizes))
    rows = np.array_split(rows, np.cumsum(row_sizes))
    tot_destinations = max(all_destinations)
    tot_origins = max(all_origins)

    for internal_time, lil_demand, row, col in zip(loading_time_steps, demand_data, rows, cols):
        vals = np.asarray(lil_demand.tocsr().data, dtype=np.float32)
        index_array_to_d = np.column_stack((row, col))
        index_array_to_o = np.column_stack((col, row))
        to_destinations = F32CSRMatrix(*csr_prep(index_array_to_d, vals, (tot_origins, tot_destinations)))
        to_origins = F32CSRMatrix(*csr_prep(index_array_to_o, vals, (tot_origins, tot_destinations)))
        origin_node_ids = np.array([all_origins[i] for i in to_destinations.get_nnz_rows()], dtype=np.uint32)
        destination_node_ids = np.array([all_destinations[i] for i in to_origins.get_nnz_rows()], dtype=np.uint32)
        static_demands.append(StaticDemand(to_origins, to_destinations,
                                           to_origins.get_nnz_rows(), to_destinations.get_nnz_rows(), origin_node_ids,
                                           destination_node_ids, internal_time))

    return DynamicDemand(static_demands, simulation_time.tot_time_steps, all_origins, all_destinations)


def __count_iter_items(iterable):
    """
    Consume an iterable not reading it into memory; return the number of items.
    """
    counter = itertools.count()
    deque(zip(iterable, counter), maxlen=0)  # (consume at C speed)
    return next(counter)


def find_nearest_centroids(X, Y, centroid_graph: nx.DiGraph):
    """
    Parameters
    ----------
    X : longitude of points epsg 4326
    Y : latitude of points epsg 4326
    centroid_graph : nx.DiGraph with existing centroids, coordinates stored as 'x' and 'y' in epsg 4326

    Returns
    -------

   """
    tot_ods = len(X)
    assert centroid_graph.graph['crs'] == 'epsg:4326'
    centroids = pd.DataFrame(
        {"x": nx.get_node_attributes(centroid_graph, "x"), "y": nx.get_node_attributes(centroid_graph, "y")}
    )
    tree = cKDTree(data=centroids[["x", "y"]], compact_nodes=True, balanced_tree=True)
    # ox.get_nearest_nodes()
    # query the tree for nearest node to each origin
    points = np.array([X, Y]).T
    centroid_dists, centroid_idx = tree.query(points, k=1)
    try:
        snapped_centroids = centroids.iloc[centroid_idx].index

    except IndexError:
        assert centroid_graph.number_of_nodes() == 0
        snapped_centroids = np.full(tot_ods, -1)  # never accessed, only triggered if centroids is empty.
        # - all distances are inf
    return snapped_centroids, centroid_dists


def _merge_gjsons(geojsons):
    """

    Parameters
    ----------
    geojsons : List of geojson Strings

    Returns
    -------
    merged geojson dict with all features

    """
    feature_lists = [loads(my_string)['features'] for my_string in geojsons]
    features = list(itertools.chain(*feature_lists))
    return {'type': 'FeatureCollection', 'features': features}
