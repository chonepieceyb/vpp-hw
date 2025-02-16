#ifndef included_vlib_edf_timestamp_h
#define included_vlib_edf_timestamp_h
#include <vlib/node.h>
#include <vlib/node_funcs.h>
#include <vppinfra/error.h>
#include <vppinfra/clib.h>
#include <vlib/vlib.h>
#include <vlib/main.h>


// 此结构体仅用于在vlib层计算vnet中提供的opaque2字段中timestamp的内存偏移
typedef struct
{
  /**
   * QoS marking data that needs to persist from the recording nodes
   * (nominally in the ingress path) to the marking node (in the
   * egress path)
   */
  struct
  {
    u8 bits;
    u8 source;
  } qos;

  u8 loop_counter;
  u8 __unused[5];

  /**
   * The L4 payload size set on input on GSO enabled interfaces
   * when we receive a GSO packet (a chain of buffers with the first one
   * having GSO bit set), and needs to persist all the way to the interface-output,
   * in case the egress interface is not GSO-enabled - then we need to perform
   * the segmentation, and use this value to cut the payload appropriately.
   */
  struct
  {
    u16 gso_size;
    /* size of L4 prototol header */
    u16 gso_l4_hdr_sz;
    i16 outer_l3_hdr_offset;
    i16 outer_l4_hdr_offset;
  };

  struct
  {
    u32 arc_next;
    union
    {
      u32 cached_session_index;
      u32 cached_dst_nat_session_index;
    };
  } nat;

  // use 8 byte unused space to store the protocol identifier
  u32 protocol_identifier;
  // wether this packet has been counted by calc_latency()
  u32 is_counted;
  // store the timestamp of the packet inconming time
  u64 timestamp;
  u32 unused[4];
} vnet_buffer_opaque2_copy_t;

// 计算并返回当前pending_frame中最大的timestamp，其加上
static_always_inline
u64 calculate_min_deadline_ts(vlib_main_t *vm, vlib_pending_frame_t *pf)
{
  u64 min_deadline_ts = ~0, time_stamp = 0;
  vlib_frame_t *f = vlib_get_frame(vm, pf->frame);
  u32 *buffer_index_arr = (u32 *) vlib_frame_vector_args (f);
  // clib_warning("[begin] f->n_vectors:%d", f->n_vectors);
  // FIXME: 目前发现 buffer_index 很大的情况，f->n_vectors 大多都为 1，可以将frame->n_vectors<=2的frame超时时间戳设为0
  if (f->n_vectors > 2) {
    for (u16 i = 0; i < f->n_vectors; i++) {
      // clib_warning("buffer_index_arr[%d]:%d", i, buffer_index_arr[i]);
      // FIXME: 存在一些frame，其中只有一个包，但其buffer_index_arr[0]为一个很大的数值，导致后续vlib_get_buffer()时出现错误，目前观测bi均在[0, 700000]之间
      // if (PREDICT_FALSE(buffer_index_arr[i] > 700000)) {
      //   vlib_node_runtime_t *rt = vec_elt_at_index (vm->node_main.nodes_by_type[VLIB_NODE_TYPE_INTERNAL],
      // 	      pf->node_runtime_index);
      //   u32 node_index = rt->node_index;
      //   vlib_node_t *node = vlib_get_node(vm, node_index);
      //   clib_warning("[bi overflow] bi: %u, at node: %s, f->n_vectors: %u", buffer_index_arr[i], node->name, f->n_vectors);
      //   continue;
      // }
      vlib_buffer_t *b = vlib_get_buffer (vm, buffer_index_arr[i]);
      u64 protocol_identifier = ((vnet_buffer_opaque2_copy_t *) (b)->opaque2)->protocol_identifier;
      // FIXME: 这里硬编码为只统计 tos/tc 为[5,8]的包(小流协议)，设计流量模板时需注意
      if (protocol_identifier < 5 || protocol_identifier > 8) {
        continue;
      }
      time_stamp = ((vnet_buffer_opaque2_copy_t *) b->opaque2)->timestamp;
      // clib_warning("buffer_index_arr[%d]:%d, protocol_identifier:%d, time_stamp:%lu", i, buffer_index_arr[i], protocol_identifier, time_stamp);
      min_deadline_ts = time_stamp < min_deadline_ts ? time_stamp : min_deadline_ts;
    }
  }
  if (min_deadline_ts != ~0)
    return min_deadline_ts + TIME_OUT_THRESHOLDER_NS;
  else 
    return ~0;
}


#endif /* included_vlib_edf_timestamp_h */