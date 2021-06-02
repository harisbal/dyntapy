#  This file is part of the Traffic Assignment Package developed at KU Leuven.
#  Copyright (c) 2020 Paul Ortmann
#  License: GNU GENERAL PUBLIC LICENSE Version 3, 29 June 2007, see license.txt
#  More information at: https://gitlab.mech.kuleuven.be/ITSCreaLab
#  or contact: ITScrealab@kuleuven.be
#
#
from dtapy.datastructures.csr import UI32CSRMatrix
import numpy as np
from dtapy.settings import parameters
from warnings import warn
from numba import njit, prange

rc_precision = parameters.route_choice.precision


# @njit(parallel=True, cache=True)
def sum_of_turning_fractions(turning_fractions: np.ndarray, out_turns: UI32CSRMatrix, link_types: np.ndarray,
                             precision: float = rc_precision):
    """
    verifies if for each link the sum of the turning
    fractions for all outgoing turns is equal to 1.
    Parameters
    ----------
    link_types: type of the links, source and sink connectors (1,-1) are excluded
    turning_fractions : array, tot_active_destinations x tot_time_steps x tot_turns
    out_turns : CSR, link x link
    precision : float

    Returns
    -------

    """
    links_to_check = np.argwhere(link_types != 0 or link_types != 1)[0]
    try:
        for t in prange(turning_fractions.shape[1]):
            for dest_id in prange(turning_fractions.shape[0]):
                for link in links_to_check:
                    tf_sum = 0.0
                    for turn in out_turns.get_row(link):
                        tf_sum += turning_fractions[dest_id, t, turn]
                    if np.abs(tf_sum - 1.0) > precision:
                        print("turning fraction sum violation for link " + str(link) +
                              " at time " + str(t) + " for destination id " + str(dest_id))
                        raise ValueError
    except ValueError:
        warn('sum_of_turning_fractions test failed')
        pass

    print('turning fraction sum test passed successfully')


nl_precision = parameters.network_loading.precision


# @njit(parallel=True, cache=True)
def continuity(cvn_up: np.ndarray, cvn_down: np.ndarray, in_links: UI32CSRMatrix,
               out_links: UI32CSRMatrix, max_delta: float = nl_precision, tot_centroids=0):
    """
    verifies for each node, destination and time step whether the sum of all
    downstream cumulatives of the incoming links equals the sum of the upstream cumulatives of all outgoing links
    Parameters
    ----------
    tot_centroids : number of centroids, assumed to be labelled as the first nodes
    cvn_up : upstream cumulative numbers, tot_time_steps x tot_links x tot_destinations
    cvn_down : downstream cumulative numbers, tot_time_steps x tot_links x tot_destinations
    in_links : CSR node x links
    out_links : CSR node x links
    max_delta : float, allowed constraint violation

    Returns
    -------
    """

    tot_time_steps = cvn_down.shape[0]
    tot_destinations = cvn_down.shape[2]
    try:
        for t in prange(tot_time_steps):
            for d in prange(tot_destinations):
                for node in range(tot_centroids, in_links.nnz_rows.size):
                    in_flow = 0.0
                    out_flow = 0.0
                    for in_link in in_links.get_nnz(node):
                        in_flow += cvn_down[t, in_link, d]
                    for out_link in out_links.get_nnz(node):
                        out_flow += cvn_up[t, out_link, d]
                    if np.abs(out_flow - in_flow) > max_delta:
                        print("continuity violation in node " + str(node) +
                              " at time " + str(t) + " for destination id " + str(d))
    except ValueError:
        warn('continuity test failed')
        pass
    print('continuity test passed successfully')


# @njit(parallel=True, cache=True)
def monotonicity(cvn_up, cvn_down):
    """

    Parameters
    ----------
    cvn_up : upstream cumulative numbers, tot_time_steps x tot_links x tot_destinations
    cvn_down : downstream cumulative numbers, tot_time_steps x tot_links x tot_destinations

    Returns
    -------

    """
    tot_time_steps = cvn_down.shape[0]
    tot_links = cvn_down.shape[1]
    tot_destinations = cvn_down.shape[2]
    try:
        for t in prange(tot_time_steps - 1):
            for link in prange(tot_links):
                for d in range(tot_destinations):
                    if cvn_up[t, link, d] > cvn_up[t + 1, link, d] or cvn_down[t, link, d] > cvn_down[t + 1, link, d]:
                        print("monotonicity violation for link " + str(link) +
                              " at time " + str(t) + " for destination id " + str(d))
                        raise ValueError
    except ValueError:
        warn('monotonicity test failed')
        pass
    print('monotonicity test passed successfully')


def storage(cvn_up: np.ndarray, cvn_down: np.ndarray, storage: np.ndarray):
    """

    Parameters
    ----------
    cvn_up : upstream cumulative numbers, tot_time_steps x tot_links x tot_destinations
    cvn_down : downstream cumulative numbers, tot_time_steps x tot_links x tot_destinations
    storage : amount of vehicles that can be kept on each link

    Returns
    -------

    """
    tot_time_steps = cvn_down.shape[0]
    tot_links = cvn_down.shape[1]
    try:
        for t in prange(tot_time_steps - 1):
            for link in prange(tot_links):
                if np.sum(cvn_up[t, link, :] - cvn_down[t, link, :]) > storage[link]:
                    print("storage violation for link " + str(link) +
                          " at time " + str(t))
                    raise ValueError
    except ValueError:
        warn('storage test failed')
        pass
    print('storage test passed successfully')
