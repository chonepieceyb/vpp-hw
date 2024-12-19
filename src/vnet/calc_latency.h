/*
 * author: LunqiZhao
 */

#ifndef __included_vnet_calc_latency_h__
#define __included_vnet_calc_latency_h__

#include <vppinfra/clib.h>
#include <vnet/vnet.h>
#include <vlib/main.h>

// RX callback to add timestamp into incoming packet
static_always_inline void
add_timestamps(vlib_main_t *vm, vlib_buffer_t *pkt, u64 now) {
  ((vnet_buffer_opaque2_t *) pkt->opaque2)->timestamp = now;
  ((vnet_buffer_opaque2_t *) pkt->opaque2)->is_counted = 0;
}

// TX callback to calculate latency statistics for each packet
static_always_inline void calc_latency (vlib_main_t *vm, vlib_buffer_t *pkt, u64 now, latency_counter_t *lat_stats, latency_counter_t *total_lat_stats, u32 pkt_bytes) {
  // avoid counting the same packet twice
  if (PREDICT_FALSE((((vnet_buffer_opaque2_t *) (pkt)->opaque2)->is_counted))) {
    return;
  }
  ((vnet_buffer_opaque2_t *) (pkt)->opaque2)->is_counted = 1;

  u64 packet_ts = ((vnet_buffer_opaque2_t *) (pkt)->opaque2)->timestamp;
  u64 packet_latency = now - packet_ts;

  // get protocal_identifier from packet opaque2 field which is set in the ip4-input and ip6-input node
  u32 protocal_identifier = ((vnet_buffer_opaque2_t *) (pkt)->opaque2)->protocol_identifier;

  // If the protocal_identifier is greater than MAX_LATENCY_TRACE_COUNT or equals 0, it is considered as invalid.
  if (PREDICT_FALSE(protocal_identifier >= MAX_LATENCY_TRACE_COUNT || protocal_identifier == 0)) {
    return;
  }

  // If the packet_latency is greater than the TIME_OUT_THRESHOULDER_NS, it is considered as timeout.
  if (packet_latency > TIME_OUT_THRESHOULDER_NS) {
    lat_stats[protocal_identifier].timeout_pkts++;
  }

  // Update the latency statistics, actually total_latency store the latency time(ns)
  lat_stats[protocal_identifier].total_pkts++;
  lat_stats[protocal_identifier].total_latency += packet_latency;
  lat_stats[protocal_identifier].total_bytes += pkt_bytes;
  total_lat_stats->total_pkts++;
  total_lat_stats->total_latency += packet_latency;
  total_lat_stats->total_bytes += pkt_bytes;

  // decrease the remaining packets count
  // vm->remaing_pkts_count--;

  return;
}

#endif /* __included_vnet_calc_latency_h__ */