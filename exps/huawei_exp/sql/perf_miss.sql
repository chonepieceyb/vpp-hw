select batch_size_setting,
       round(avg(L1_dcache_loads), 0) as L1_dcache_loads,
       round(avg(L1_dcache_load_misses), 0) as L1_dcache_load_misses,
       round(avg(L1_dcache_store), 0) as L1_dcache_store,
       round(avg(icache_hit), 0) as icache_hit,
       round(avg(icache_misses), 0) as icache_misses,
       round(avg(icache_ifdata_stall), 0) as icache_ifdata_stall,
       round(avg(LLC_loads), 0) as LLC_loads,
       round(avg(LLC_load_misses), 0) as LLC_load_misses,
       round(avg(LLC_stores), 0) as LLC_stores,
       round(avg(L2_RQSTS_ALL_DEMAND_MISS), 0) as L2_RQSTS_ALL_DEMAND_MISS
from vpp_perf_data
group by batch_size_setting