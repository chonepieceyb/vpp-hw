-- SQLite
SELECT name, batch_size_setting, batch_size_actual,
       round(avg(L1I_cache_miss), 5) as L1I,
       round(avg(L1D_cache_miss), 5) as L1D,
       round(avg(L2_cache_miss), 5) as L2,
       round(avg(clocks), 5) as clocks,
       round(avg(throughput_actual), 5) as throughput_actual,
       round(avg(avg_lat_ns), 5) as avg_lat_ns
FROM vpp_exp_data
where name in ('ip4-input-no-checksum', 'ip6-input', 'nat-pre-in2out', 'ip4-inacl')
  and L1I_cache_miss is not null
group by name, batch_size_setting, round(batch_size_actual);
