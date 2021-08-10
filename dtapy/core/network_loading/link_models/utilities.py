#  This file is part of the Traffic Assignment Package developed at KU Leuven.
#  Copyright (c) 2020 Paul Ortmann
#  License: GNU GENERAL PUBLIC LICENSE Version 3, 29 June 2007, see license.txt
#  More information at: https://gitlab.mech.kuleuven.be/ITSCreaLab
#  or contact: ITScrealab@kuleuven.be
#
#
#
import numpy as np
from dtapy.core.network_loading.link_models.i_ltm_cls import ILTMNetwork
from dtapy.visualization import show_dynamic_network
from dtapy.core.supply import Network
from dtapy.core.time import SimulationTime
from numba import njit, prange, objmode
from numba.typed import List
from dtapy.settings import parameters

epsilon = parameters.network_loading.epsilon


@njit(cache=True, parallel=True)
def cvn_to_flows(cvn_down):
    """

    Parameters
    ----------
    cvn :

    Returns
    -------

    """
    tot_time_steps = cvn_down.shape[0]
    tot_links = cvn_down.shape[1]
    cvn_down = np.sum(cvn_down, axis=2)
    flows = np.zeros((tot_time_steps, tot_links), dtype=np.float32)
    flows[0, :] = cvn_down[0, :]
    for time in prange(1, tot_time_steps):
        flows[time, :] = np.abs(-cvn_down[time - 1, :] + cvn_down[time, :])
    return flows


# @njit(cache = True, parallel=True)
def cvn_to_travel_times_old(cvn_up: np.ndarray, cvn_down: np.ndarray, time: SimulationTime, network: Network,
                            method='backward', dnl_precision=parameters.network_loading.precision):
    # DEPRECIATED
    """
    Calculates travel times per link based on single commodity cumulative vehicle numbers
    Parameters
    ----------
    cvn_up :2D array, tot_time_steps x tot_links
    cvn_down : 2D array, tot_time_steps x tot_links
    time : SimulationTime
    network : Network
    method : only 'forward' for now

    Returns
    -------
    travel_times: 2D array, tot_time_steps x tot_links
    If method == 'forward':
        travel_times[t,link] is the travel time experienced by the first vehicle
         that entered the link during the interval [t, t +dt]
    If method == 'backward':
        travel_times[t,link] is the travel time experienced by the last vehicle
         that left the link during the interval [t, t +dt]

    TODO: explore these different approaches.. how do they differ from one another and how do they affect route choice?

    forward with the last vehicle does not produce accurate results,
    due to i-ltm vehicle chopping with dissipating flows.
    If method == 'backward_first':
        travel_times[t,link] is the travel time experienced by the first vehicle
         that left the link during the interval [t, t +dt]

    """
    travel_times = np.zeros((time.tot_time_steps, network.tot_links), dtype=np.float32)
    if method == 'forward':
        # TODO: more testing of this
        # This doesn't adequately capture costs that are generated by spillback on the connector
        for t in prange(time.tot_time_steps):
            for link in prange(network.tot_links):
                if not network.links.link_type[link] == -1 or network.links.link_type[link] == 1:
                    if cvn_up[t, link] - cvn_up[t - 1, link] > 1 \
                            or (t == 0 and cvn_up[0, link] > 1):
                        found_cvn = False
                        cvn = cvn_up[t - 1, link]
                        if t == 0:
                            cvn = 1  # somewhat simplified as the time of entering is no longer t==0 anymore..
                        for t2 in range(t, time.tot_time_steps, 1):
                            if cvn_down[t2, link] > cvn:
                                found_cvn = True
                                if t2 == 0:
                                    departure_time = 1 - \
                                                     (cvn_down[t2, link] - cvn) * 1 / (
                                                         cvn_down[t2, link])
                                else:
                                    departure_time = 1 - \
                                                     (cvn_down[t2, link] - cvn) * 1 / (
                                                             cvn_down[t2, link] -
                                                             cvn_down[
                                                                 t2 - 1, link])
                                    departure_time = (departure_time + t2 - 1)
                                travel_times[t, link] = (departure_time - t) * time.step_size
                                break
                            elif cvn_down[t2, link] == cvn:
                                found_cvn = True
                                travel_times[t, link] = (t2 - t) * time.step_size
                                break
                        if not found_cvn:
                            # vehicle unable to leave network during simulation
                            travel_times[t, link] = travel_times[t - 1, link]

                travel_times[t, link] = max(travel_times[t, link],
                                            np.float32((network.links.length[link] / network.links.v0[link])))
    elif method == 'backward':
        # TODO: check this again for correctness
        for t in prange(time.tot_time_steps):
            for link in prange(network.tot_links):
                if not network.links.link_type[link] == -1 or network.links.link_type[link] == 1:
                    if cvn_down[t, link] - cvn_down[t - 1, link] > 1 \
                            or (t == 0 and cvn_down[0, link] > 1):
                        cvn = cvn_down[t, link]
                        for t2 in range(t + 1, -1, -1):
                            if t2 - 1 == -1:
                                # if there is a zero division error here, we've got negative queues..
                                arrival_time = 1 - \
                                               (cvn_up[0, link] - cvn) * 1 / (
                                                   cvn_up[0, link])
                                travel_times[t, link] = (t + 1 - arrival_time) * time.step_size
                            elif cvn_up[t2 - 1, link] < cvn:
                                if t2 == time.tot_time_steps:
                                    if cvn - cvn_up[t2 - 1, link] > dnl_precision:
                                        raise ValueError('cvn_up cannot be smaller than cvn_down for a given time step')
                                    else:
                                        continue
                                if not cvn < cvn_up[t2, link]:
                                    # numerical precision issue, may report travel time incorrectly
                                    continue
                                arrival_time = 1 + \
                                               (cvn_up[t2, link] - cvn) * 1 / (
                                                       cvn_up[t2 - 1, link] -
                                                       cvn_up[
                                                           t2, link])
                                arrival_time = (arrival_time + t2 - 1)
                                travel_times[t, link] = (t - arrival_time) * time.step_size
                                break
                            elif cvn_up[t2 - 1, link] == cvn:
                                arrival_time = t2 - 1
                                travel_times[t, link] = (t - arrival_time) * time.step_size
                                break

                travel_times[t, link] = max(travel_times[t, link],
                                            np.float32((network.links.length[link] / network.links.v0[link])))
    else:
        raise NotImplementedError

    return travel_times


def cvn_to_travel_times(cvn_up: np.ndarray, cvn_down: np.ndarray, con_down: np.ndarray, time: SimulationTime,
                        network: Network):
    """
    Calculates travel times per link based on single commodity cumulative vehicle numbers
    Parameters
    ----------
    cvn_up :2D array, tot_time_steps x tot_links
    cvn_down : 2D array, tot_time_steps x tot_links
    time : SimulationTime
    network : Network

    Returns
    -------
    travel_times: 2D array, tot_time_steps x tot_links

    """
    travel_times = np.zeros((time.tot_time_steps, network.tot_links), dtype=np.float32)
    # travel times of a vehicle departing as the first vehicle on the discretization points

    # the first vehicles of a time slice that enter a link typically do not experience delays,
    # since new capacity was made available
    # so these costs are generated by interpolation of departures that are more representative in congestion
    # if there was congestion downstream we trace the arrival time of the last departing vehicle of a given time period
    # what we get are travel times for each of these arrival times that are not aligned with the time steps
    # to get the actual travel times on the time steps themselves we need to interpolate again
    time_steps = np.arange(time.tot_time_steps)
    for link in prange(network.tot_links):
        ff_tt = np.float32((network.links.length[link] / network.links.v0[link]))
        never_congested=False
        if network.links.link_type[link] == -1:
            # no consideration of exiting connector costs
            never_congested =True
        else:
            congested_periods = np.nonzero(con_down[:, link])[0]
            if congested_periods.size==0: # all time periods for this link uncongested
                never_congested = True
            else:
                # adding free flow travel time for t==0
                pointer = 0
                arrival_times = List()
                # time when the vehicle that was registered downstream entered the link
                experienced_travel_times=List()
                # experienced travel time of the vehicle that was registered downstream
                for t in time_steps:
                    if t == congested_periods[pointer]:
                        k = np.where(np.logical_and(cvn_up[1:,link] >= cvn_down[t,link], cvn_up[:-1,link] < cvn_down[t,link]))[0]
                        try:
                            k = k[0]
                            arrival_times.append(np.interp(cvn_down[t, link], cvn_up[k:k+2,link],np.array([k+1,k+2]) ))
                        except IndexError:
                            if cvn_down[t,link]>cvn_up[0,link]:
                                raise AssertionError
                            arrival_times.append(cvn_down[t,link]/cvn_up[0,link])
                        experienced_travel_times.append(max((t + 1 - arrival_times[-1])*time.step_size, ff_tt))
                        if pointer<congested_periods.size-1:
                            pointer += 1
                    else:
                        arrival_times.append((t + 1) - ff_tt)
                        experienced_travel_times.append(ff_tt)

                if len(set(arrival_times)) < len(arrival_times): # arrival times are not unique,
                    # conflicting travel times ..
                    # ugly sorting code, but gets the job done - shouldn't be called frequently
                    sorted_arr_times = sorted(arrival_times)
                    # sorting to identify duplicates
                    for _id, val in enumerate(sorted_arr_times):
                        if val == sorted_arr_times[_id + 1]:
                            # duplicate found
                            indices = np.where(arrival_times == val)[0]
                            congested_indices = List()
                            free_flow_indices = List()
                            for index in indices:
                                # identifying congested and free flow indices among equal arrival times
                                if con_down[index, link]:
                                    congested_indices.append(index)
                                else:
                                    free_flow_indices.append(index)
                            for index in congested_indices:
                                # overwriting congested travel times with free flow values, higher accuracy
                                experienced_travel_times[index, link] = ff_tt

                        # flattening the travel times for arrivals in the last interval
                        experienced_travel_times[-1] = experienced_travel_times[-2]
        if never_congested:
            travel_times[:, link]=ff_tt
        else:
            travel_times[:, link] = np.interp(time_steps,arrival_times, experienced_travel_times)

    return travel_times



def _debug_plot(results, network: ILTMNetwork, time, title='None', toy_network=True):
    from dtapy.__init__ import current_network
    flows = cvn_to_flows(results.cvn_down)
    cur_queues = np.sum(results.cvn_up, axis=2) - np.sum(results.cvn_down, axis=2)  # current queues
    show_dynamic_network(current_network, time, toy_network=toy_network, title=title, link_kwargs=
    {'cvn_up': results.cvn_up, 'cvn_down': results.cvn_down, 'vind': network.links.vf_index,
     'wind': network.links.vw_index, 'flows': flows, 'current_queues': cur_queues})
