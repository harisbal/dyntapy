#  This file is part of the traffic assignment code base developed at KU Leuven.
#  Copyright (c) 2020 Paul Ortmann
#  License: GNU GENERAL PUBLIC LICENSE Version 3, 29 June 2007, see license.txt
#  More information at: https://gitlab.kuleuven.be/ITSCreaLab
#  or contact: ITScrealab@kuleuven.be
#
#
#
from dtapy.core.network_loading.link_models.i_ltm_cls import ILTMNetwork, ILTMState
from dtapy.core.demand import Demand, InternalDynamicDemand
from dtapy.core.time import SimulationTime
import numpy as np
from dtapy.settings import parameters
from numba import njit
from numba.typed import List
from dtapy.core.network_loading.node_models.orca_nodel_model import orca_node_model as orca

gap = parameters.network_loading.gap
node_model_str = parameters.network_loading.node_model


# for t in range(time.tot_time_steps):
#     if dynamic_demand.is_loading(t):
#         demand: Demand = dynamic_demand.get_demand(t)
#         for origin in demand.origins:
#             for connector in network.nodes.out_links.get_nnz(origin):
#                 for flow, destination, fraction in zip(demand.to_destinations.get_row(origin),
#                                                        demand.to_destinations.get_nnz(origin),
#                                                        connector_choice.get_row(connector)):


# @njit
def i_ltm(network: ILTMNetwork, dynamic_demand: InternalDynamicDemand, results: ILTMState, time: SimulationTime,
          turning_fractions, connector_choice):
    tot_time_steps = time.tot_time_steps
    step_size = time.step_size

    tot_links = network.tot_links
    tot_nodes = network.tot_nodes
    tot_destinations = dynamic_demand.all_active_destinations.size
    tot_out_links = network.nodes.tot_out_links
    tot_in_links = network.nodes.tot_in_links
    max_out_links = np.max(network.nodes.tot_out_links)
    max_in_links = np.max(network.nodes.tot_in_links)
    in_links = network.nodes.in_links
    out_links = network.nodes.out_links

    to_node = network.links.to_node
    from_node = network.links.from_node
    cap = network.links.capacity
    kjm = network.links.k_jam
    length = network.links.length
    vind = network.links.vf_index
    vrt = network.links.vf_ratio
    wind = network.links.vw_index
    wrt = network.links.vw_ratio

    # local rename results properties
    # check for warm and cold starting is done in i_ltm_setup.py

    nodes_2_update = results.nodes_2_update
    cvn_up, cvn_down = results.cvn_up, results.cvn_down
    con_up, con_down = results.con_up, results.con_down
    marg_comp = results.marg_comp

    # allocate memory to local variables
    tot_receiving_flow = np.zeros(max_out_links)
    sending_flow = np.zeros((max_in_links, tot_destinations))  # what the in_links would like to send
    temp_sending_flow = np.empty((max_in_links, tot_destinations))  # what they actually get to send
    tot_sending_flow = np.empty(max_in_links)
    # variables with local_x always concern structures for the node model and it's surrounding links/turns
    receiving_flow = np.empty((max_out_links, tot_destinations))

    local_turning_flows = np.empty((max_in_links, max_out_links))
    local_turning_fractions = np.empty((max_in_links, max_out_links))

    # forward implicit scheme
    # go sequentially over each time step
    mean_it_iltm = 0
    max_it_iltm = 0
    tot_nodes_updates = 0  # tracking node updates over the entire DNL
    delta_change = np.zeros(tot_nodes, dtype=np.float32)
    # part of these assignments may be added eventually, let's see what we actually need with our TF notation

    for t in range(1, tot_time_steps):
        if not nodes_2_update[:, t].any():
            continue
        # sending and receiving flow to be initialized for all links
        receiving_flow_init = np.full(tot_links, True)
        sending_flow_init = np.full(tot_links, True)

        if dynamic_demand.is_loading(t):  # check if any origins are sending flow into the network this time step
            current_demand: Demand = dynamic_demand.get_demand(t)
            __load_origin_flows(current_demand, connector_choice, nodes_2_update, t, cvn_up, temp_sending_flow,
                                tot_nodes_updates,
                                out_links, cap, step_size, con_up, vind, tot_time_steps, to_node)

        # njit tests pass until here without failure
        first_intersection = dynamic_demand.all_centroids.size  # the first C nodes are centroids
        node_processing_order = List(np.arange(first_intersection, tot_nodes))

        cur_nodes_2_update = len(node_processing_order)  # remaining nodes that need updating for the current iteration
        # TODO: maintaining nodes 2 update as priority queue?
        it = 0  # counter for current iteration
        while it < max_it_iltm and cur_nodes_2_update > 0:
            it = it + 1
            tot_nodes_updates = tot_nodes_updates + cur_nodes_2_update
            #  _______ main loops here, optimization crucial ______
            for node in node_processing_order:
                local_in_links = in_links.get_nnz(node)
                local_out_links = out_links.get_nnz(node)
                delta_change[node] = 0
                calc_sending_flows(local_in_links, cvn_up, t, cvn_down, vind, vrt, cap, sending_flow,
                                   temp_sending_flow, tot_sending_flow, sending_flow_init)
                calc_receiving_flows(local_out_links, wrt, wind, kjm, length, cap, t, tot_receiving_flow, cvn_down,
                                     cvn_up,
                                     receiving_flow_init, receiving_flow, step_size)
                calc_turning_flows(tot_out_links, local_turning_fractions,
                                   network.nodes.turn_based_in_links.get_row(node),
                                   network.nodes.turn_based_out_links.get_row(node),
                                   network.nodes.turn_based_out_links.get_nnz(node), temp_sending_flow,
                                   local_turning_flows, turning_fractions, t)
                # todo: order arguments in some logical fashion and document these functions ..
                tot_sending_flow[:len(local_in_links)] = np.sum(temp_sending_flow, 1)
                # Node model call
                local_turning_capacity = None
                if node_model_str == 'orca':
                    result_turning_flows = orca(temp_sending_flow, local_turning_fractions, local_turning_flows,
                                                receiving_flow,
                                                local_turning_capacity, local_in_links)


def __load_origin_flows(current_demand, connector_choice, nodes_2_update, t, cvn_up, tmp_sending_flow,
                        tot_nodes_updates, out_links, cap,
                        step_size, con_up, vind, tot_time_steps, to_node):
    for origin in current_demand.origins:
        if nodes_2_update[t, origin]:
            tot_nodes_updates += 1
            for index, connector in np.ndenumerate(out_links):
                tmp_sending_flow[0, :] = cvn_up[t - 1, connector, :]
                for flow, destination, fraction in zip(current_demand.to_destinations.get_row(origin),
                                                       current_demand.to_destinations.get_nnz(origin),
                                                       connector_choice.get_row(connector)):
                    tmp_sending_flow[0, destination] += flow * fraction

                if np.sum(np.abs(tmp_sending_flow[0, :] - cvn_up[t - 1, connector, :])) > gap:
                    nodes_2_update[min(tot_time_steps, t + 1), origin] = True
                    cvn_up[t, connector, :] = tmp_sending_flow[:, 0]
                    if np.sum(cvn_up[t, connector, :] - cvn_up[t - 1, connector, :]) < cap[connector] * step_size:
                        con_up[t, connector] = False
                    else:
                        con_up[t, connector] = True

                if vind[connector] == -1:
                    nodes_2_update[t, to_node[connector]] = True
                else:
                    try:
                        nodes_2_update[t - vind[connector] - 1, to_node[connector]] = True
                        nodes_2_update[t - vind[connector], to_node[connector]] = True
                    except Exception:
                        assert t - vind[connector] > tot_time_steps
                        if t - vind[connector] - 1 == tot_time_steps:
                            nodes_2_update[tot_time_steps, to_node[connector]] = True
                        else:
                            print('Simulation time period is too short for given demand.'
                                  ' Not all vehicles are able to exit the network')


def calc_sending_flows(local_in_links, cvn_up, t, cvn_down, vind, vrt, cap, sending_flow,
                       tot_sending_flow, sending_flow_init):
    for _id, link in enumerate(local_in_links):
        if sending_flow_init[link]:
            sending_flow_init[link] = False
            sending_flow[_id, :] = cvn_up[max(0, t + vind[link]), link, :] * 1 - vrt[link] - cvn_down[t - 1,
                                                                                             link, :]
            if vind[link] < -1:  # for all links with free flow travel time larger than dt we interpolate
                sending_flow[_id, :] = sending_flow[_id, :] + vrt[link] * cvn_up[max(0, t + vind[link] + 1),
                                                                          link, :]
        if vind[link] == -1:
            sending_flow[_id, :] = sending_flow[_id, :] + vrt[link] * cvn_up[t, link, :]
        sending_flow[_id, :][sending_flow[_id, :] < 0] = 0  # setting negative sending flows to 0
        tot_sending_flow[_id] = min(cap[link], np.sum(sending_flow[_id, :]))


def calc_receiving_flows(local_out_links, wrt, wind, kjm, length, cap, t, tot_receiving_flow, cvn_down, cvn_up,
                         receiving_flow_init, step_size):
    for _id, link in enumerate(local_out_links):
        if receiving_flow_init[link]:
            receiving_flow_init[link] = False
            tot_receiving_flow[_id] = \
                np.sum(cvn_down[max(1, t + wind[link]), link, :]) * \
                (1 - wrt[link] - np.sum(cvn_up[t - 1, link, :]) + kjm[link] * length[link])
            if wind[link] < -1:
                tot_receiving_flow[_id] = tot_receiving_flow[_id] + wrt[link] * np.sum(
                    cvn_down[max(0, t + wind[link] + 1), link, :])
                # TODO: check if this offset is correct
        # if rf_down_cvn_db[link]<np.float32(pow(10,-10)):
        #   raise ValueError('negative RF')
        if tot_receiving_flow[_id] < 0:
            tot_receiving_flow[_id] = 0
        if wind[link] == -1:
            tot_receiving_flow[_id] = tot_receiving_flow[_id] + wrt[link] * np.sum(cvn_down[t, link, :])
        tot_receiving_flow[_id] = min(cap[link] * step_size, tot_receiving_flow[_id])


def calc_turning_flows(tot_out_links, local_turning_fractions, turn_in_links, turn_out_links, turns, local_sending_flow,
                       local_turning_flows, turning_fractions, t):
    """
    calculate the local turning flows

    Parameters
    ----------
    tot_out_links : int, number of out links of local node
    local_turning_fractions : array, dim>= local_in_links x local_out_links, row sum is 1 for row 0,..,k with k
    the number of in_links for the node
    turn_in_links : array, local in_link labels for all turns crossing the node
    turn_out_links : array, local out_link labels for all turns crossing the node
    turns : array, global turn ids of crossing turns
    local_sending_flow : array, dim>= local_in_links x tot_destinations
    local_turning_flows : array, dim>= local_in_links x local_out_links
    turning_fractions : array, dim tot_time_steps x tot_turns x destinations
    t : scalar, current time_step
    """
    #
    if tot_out_links == 1:
        # simple merge
        local_turning_fractions[:, 1] = 1
    else:
        # multiple outgoing links
        for in_link, out_link, turn in zip(turn_in_links, turn_out_links, turns):
            # in_link and out_link values here start at zero as they reference
            # the internal labelling for the node model
            local_turning_flows[in_link, out_link] = local_turning_flows[in_link, out_link] + np.sum(
                local_sending_flow[in_link, :] * turning_fractions[t - 1, turn, :])


def update_cvns_and_delta_n(result_turning_flows, node, sending_flow, temp_sending_flow, receiving_flow, tot_out_links,
                            in_links, out_links, total_sending_flow, con_down, in_link_capacity, time_step, t,
                            cvn_down, wind, wrt, from_node, nodes_2_update, delta_change, tot_time_steps):
    update_node = False
    result_tot_sending_flow = np.sum(result_turning_flows, axis=1)
    receiving_flow[:tot_out_links, :] = 0
    for _id, in_link in in_links:
        if np.any(total_sending_flow[_id, :]) > 0:
            if result_tot_sending_flow[_id] < total_sending_flow[_id] \
                    or np.abs(result_tot_sending_flow[_id] - in_link_capacity[_id] * time_step) < gap:
                con_down[in_link] = True
                temp_sending_flow[_id, :] = sending_flow[_id, :] / total_sending_flow[_id] * result_tot_sending_flow[
                                                                                             _id, :]
            else:
                con_down[in_link] = False
                temp_sending_flow[_id, :] = sending_flow[_id, :]
            update_in_link = np.sum(np.abs(
                cvn_down[t, in_link, :] - (cvn_down[t - 1, in_link, :] + temp_sending_flow[_id, :]))) < gap
            update_node = update_in_link or update_node
            if update_in_link:
                if wind[in_link] == -1:
                    nodes_2_update[t, from_node[in_link]] = True
                    delta_change[from_node[in_link]] = delta_change[from_node[in_link]] + wrt[in_link] * np.sum(
                        np.abs(cvn_down[t, in_link, :] - (cvn_down[t - 1, in_link, :] + temp_sending_flow[_id, :])))
                else:
                    nodes_2_update[from_node[in_link], min(tot_time_steps + 1, t - wind[in_link]) - 1] = True
                    nodes_2_update[from_node[in_link], min(tot_time_steps + 1, t - wind[in_link])] = True
            active_destinations = np.where(sending_flow[_id, :] > 0)
            if tot_out_links==1:
                for destination in active_destinations:
                    receiving_flow[0,destination] = receiving_flow[0,destination] + temp_sending_flow[_id, destination]
            else:
                outIndex = outTF_index(posTF(n):posTF(n) + nTF(n) - 1);
                turn_index = find(inIndex == l_index);
                l_index2 = outIndex(turn_index);
                temp_receivingFlow(l_index2, active_d) = temp_receivingFlow(l_index2, active_d) + temp_sendingFlow(
                    l_index, active_d). * TF_P(posTF(n) + turn_index - 1, active_d, t - 1);

