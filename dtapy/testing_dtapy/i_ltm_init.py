#  This file is part of the Traffic Assignment Package developed at KU Leuven.
#  Copyright (c) 2020 Paul Ortmann
#  License: GNU GENERAL PUBLIC LICENSE Version 3, 29 June 2007, see license.txt
#  More information at: https://gitlab.mech.kuleuven.be/ITSCreaLab
#  or contact: ITScrealab@kuleuven.be
#
#
#
from dtapy.core.jitclasses import SimulationTime
from dtapy.demand import build_demand, generate_od_fixed, generate_od_xy, create_centroids
from dtapy.network_data import get_from_ox_and_save
import numpy as np
from dtapy.assignment import Assignment
from dtapy.core.network_loading.i_ltm_setup import i_ltm_setup
(g, deleted) = get_from_ox_and_save('Gent')
gjson=generate_od_xy(10, 'Gent')
create_centroids(gjson, g)

print(f'number of nodes{g.number_of_nodes()}')
start_time = 6  # time of day in hrs
end_time = 12
demands = [generate_od_fixed(g.number_of_nodes(), 20), generate_od_fixed(g.number_of_nodes(),30, seed=1)]
insertion_times = np.array([6, 7])
ltm_dt = 0.25  # ltm timestep in hrs
simulation_time = SimulationTime(start_time, end_time, ltm_dt)
demand_simulation = build_demand(demands, insertion_times, simulation_time, g.number_of_nodes())
assignment=Assignment(g, demand_simulation, simulation_time)
print('init passed successfully')
print('hi')
