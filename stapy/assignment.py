#  This file is part of the traffic assignment code base developed at KU Leuven.
#  Copyright (c) 2020 Paul Ortmann
#  License: GNU GENERAL PUBLIC LICENSE Version 3, 29 June 2007, see license.txt
#  More information at: https://gitlab.kuleuven.be/ITSCreaLab
#  or contact: ITScrealab@kuleuven.be
#
#
import numpy as np
from collections import defaultdict
from scipy.sparse import csr_matrix
from numba.typed import Dict, List
from itertools import count
import networkx as nx
from stapy.algorithms.graph_utils import make_forward_stars, make_backward_stars
from utilities import log
from scipy.sparse import lil_matrix
from stapy.demand import build_demand_structs


class StaticAssignment:
    """This class has no value when instantiated on it's own,
     it merely sets up the state variables/interfaces to networkx"""

    def __init__(self, g: nx.DiGraph, od_matrix):
        """

        Parameters
        ----------
        g : nx.DiGraph
        od_matrix : array like object
            Dimensions should be nodes x nodes of the nx.DiGraph in the Assignment object
        """
        self.adj_edge_list, self.node_map_to_nx, self.link_flows, \
        self.link_ff_times, self.link_costs, self.link_capacities, self.sparse_od_matrix, self.destinations, \
        self.demand_dict, self.edge_map, self.od_flow_vector, self.inverse_edge_map, self.number_of_od_pairs = \
            None, None, None, None, None, None, None, None, None, None, None, None, None
        self.g = g
        self.node_order = self.g.number_of_nodes()
        self.edge_order = self.g.number_of_edges()
        self.node_data=defaultdict(dict)
        # dict of dict with outer dict keyed by edges (u,v) and inner dict as data
        # to be dumped into the nx.DiGraph as key value pairs
        self.transform_graph_data()
        self.forward_star = make_forward_stars(adj_list=self.adj_edge_list, number_of_nodes=self.node_order)
        self.backward_star= make_backward_stars(adj_list=self.adj_edge_list, number_of_nodes=self.node_order)
        self.set_od_matrix(od_matrix)
        self.g.graph['iterations'] = []
        self.g.graph['gaps'] = []
        # check labelling of the nodes in nx !
        log('Assignment object initialized!')
        print('init passed sucessfully')
    def transform_graph_data(self):
        """
        routine to consolidate existing link_ids and labelling logic
        Returns
        -------
        adjacency stores node and link ids in assignment reference e.g. adjacency[link_id](node_id,node_id) with
        labelling starting at 0
        translation_link_ids_nx stores the same information in reference of the underlying nx graph,
        e.g. translation_link_ids_nx[link_id]=(u,v) with u and v being node indices for self.g
        note that 'link_id' always refers to the assignment ids as the nx dicts references nodes by key (u,v)
        """
        self.adj_edge_list = List()
        for i in range(self.edge_order): self.adj_edge_list.append((0, 0))
        self.edge_map, self.inverse_edge_map = Dict(), Dict()
        self.translation_link_ids_nx = [None for _ in range(self.edge_order)]
        self.node_map_to_nx = [None for _ in range(self.node_order)]
        self.link_flows, self.link_capacities, self.link_ff_times, self.link_costs = \
            (np.zeros(self.g.number_of_edges()) for _ in range(4))
        counter = count()
        for node_id, u in enumerate(self.g.nodes):
            self.g.nodes[u]['_id'] = node_id
            self.node_map_to_nx[node_id] = u
            for v in self.g.succ[u]:
                link_id = next(counter)
                self.g[u][v]['_id'] = link_id
                self.translation_link_ids_nx[link_id] = (u, v)
                self.link_capacities[link_id] = self.g[u][v]['capacity']
                self.link_ff_times[link_id] = self.g[u][v]['travel_time']
        for u, v, link_id in self.g.edges.data('_id'):
            _u, _v = self.g.nodes[u]['_id'], self.g.nodes[v]['_id']
            self.adj_edge_list[link_id] = _u, _v
            self.edge_map[(_u, _v)] = link_id
            self.inverse_edge_map[link_id] = (_u, _v)

    def set_od_matrix(self, od_matrix):
        """
        sets OD matrix for assignment object, calculates production and attraction of nodes
        and writes results into node_data (to be written back)
        Parameters
        ----------
        od_matrix : array like object
            Dimensions should be nodes x nodes of the nx.DiGraph in the Assignment object

        Returns
        -------

        """
        assert isinstance(od_matrix, lil_matrix)
        assert od_matrix.sum() > 0
        assert od_matrix.shape == (self.g.number_of_nodes(), self.g.number_of_nodes())
        self.demand_dict, self.od_flow_vector = build_demand_structs(od_matrix)
        self.od_matrix = od_matrix.tocsr(copy=True)
        self.sparse_od_matrix = csr_matrix(self.od_matrix)
        originating_traffic = self.sparse_od_matrix.sum(axis=1)  # summing all rows
        destination_traffic = self.sparse_od_matrix.sum(axis=0).transpose()  # summing all columns
        for i, d in enumerate(originating_traffic):
            d = float(d)
            if d > 0:
                self.node_data[i]['originating_traffic'] = float(d)
        for i, d in enumerate(destination_traffic):
            d = float(d)
            if d > 0:
                self.node_data[i]['destination_traffic'] = float(d)

    def write_back(self):
        t = self.node_map_to_nx
        for u, v in self.g.edges:
            self.g[u][v]['flow'] = 0
        for _v, data in self.node_data.items():
            for key, value in data.items():
                self.g.nodes[t[_v]][f'{key}'] = float(value)
        self.node_data=Dict()
        for (u, v), cost, flow in zip(self.translation_link_ids_nx, np.round_(self.link_costs, decimals=2), np.round_(self.link_flows, decimals=2)):
            self.g[u][v]['costs'] = float(cost)
            self.g[u][v]['flow'] = float(flow)

    def store_iteration(self, flow_vector, gap):
        self.g.graph['iterations'].append(flow_vector)
        self.g.graph['gaps'].append(gap)

    def construct_demand_graph(self):
        # this can surely be made more efficient, multiple writes per od ..
        assert self.demand_dict is not None
        demand_graph = nx.DiGraph()
        assert 'name' in self.g.graph
        assert 'crs' in self.g.graph
        demand_graph.graph['name']=self.g.graph['name']
        demand_graph.graph['crs']=self.g.graph['crs']
        for origin in self.demand_dict:
            (destinations, flows) = self.demand_dict[origin]
            for destination, flow in zip(destinations, flows):
                v = self.node_map_to_nx[destination]
                u = self.node_map_to_nx[origin]
                demand_graph.add_edge(u, v, flow=flow)
                demand_graph.nodes[u]['_id'] = origin
                demand_graph.nodes[u]['y'] = self.g.nodes[u]['y']
                demand_graph.nodes[u]['x'] = self.g.nodes[u]['x']
                demand_graph.nodes[v]['y'] = self.g.nodes[v]['y']
                demand_graph.nodes[v]['x'] = self.g.nodes[v]['x']
                demand_graph.nodes[v]['_id'] = destination
                demand_graph.nodes[u]['osmid'] = int(u)
                demand_graph.nodes[v]['osmid'] = int(v)
                demand_graph.nodes[u]['originating_traffic'] = self.node_data[origin]['originating_traffic']
                demand_graph.nodes[v]['destination_traffic'] = self.node_data[destination]['destination_traffic']
        return demand_graph


class DynamicAssignment:
    pass

