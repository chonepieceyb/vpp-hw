#ifndef PROTOCOL_NODE_FN_H
#define PROTOCOL_NODE_FN_H

#include "vppinfra/clib.h"
#define DUAL_PKT_PROCESS_FN(plugin_name)                                       \
  do {                                                                         \
    u64 sum = 0;                                                               \
    for (int index = 0; index < b0->current_length - 16; index++) {            \
      u64 *pos;                                                                \
      pos = vlib_buffer_get_current(b0);                                       \
      u64 num = *(u64 *)pos;                                                   \
      sum = sum + num;                                                         \
    }                                                                          \
    plugin_name##_hash[0] = sum;                                      \
    sum = 0;                                                                   \
    for (int index = 0; index < b1->current_length - 16; index++) {            \
      u64 *pos;                                                                \
      pos = vlib_buffer_get_current(b1);                                       \
      u64 num = *(u64 *)pos;                                                   \
      sum = sum + num;                                                         \
    }                                                                          \
    plugin_name##_hash[1] = sum;                                      \
  } while (0)

#define SINGLE_PKT_PROCESS_FN(plugin_name)                                     \
  do {                                                                         \
    u64 sum = 0;                                                               \
    for (int index = 0; index < b0->current_length - 16; index++) {            \
      u64 *pos;                                                                \
      pos = vlib_buffer_get_current(b0);                                       \
      u64 num = *(u64 *)pos;                                                   \
      sum = sum + num;                                                         \
    }                                                                          \
    plugin_name##_hash[0] = sum;                                      \
  } while (0)


typedef struct {
  u32 next_index;
  u8 src_ip[4];
  u8 dst_ip[4];
  u16 current_length;
} protocol_trace_t;

typedef enum {
  CHAIN_NEXT_NODE,
  PROTOCOL_N_NEXT,
} protocol_next_t;


#define DECLARE_PROTOCOL_NODE(pto_node_name, pto_next_node_name)    \
extern vlib_node_registration_t pto_node_name##_node; \
static u64 pto_node_name##_hash[4];     \
static u8 * pto_node_name##_format_ip_address(u8 *s, va_list *args) {   \
  u8 *a = va_arg(*args, u8 *);                                      \
  return format(s, "%3u.%3u.%3u.%3u", a[0], a[1], a[2], a[3]);      \
}                                                                   \
static u8 *format_##pto_node_name##_trace(u8 *s, va_list *args) {     \
  CLIB_UNUSED(vlib_main_t * vm) = va_arg(*args, vlib_main_t *);     \
  CLIB_UNUSED(vlib_node_t * node) = va_arg(*args, vlib_node_t *);   \
  protocol_trace_t *t = va_arg(*args, protocol_trace_t *);        \
  s = format(s, #pto_node_name ": next index %d\n", t->next_index);       \
  s = format(s, "  src_ip %U -> dst_ip %U", pto_node_name##_format_ip_address, t->src_ip, \
             pto_node_name##_format_ip_address, t->dst_ip);                               \
  s = format(s, "  current_length: %d", t->current_length);                 \
  return s;                                                             \
}                                                                       \
typedef enum {                                                        \
  pto_node_name##_PROCESSED = 0,                                                   \
  pto_node_name##_N_ERROR,                                                  \
} pto_node_name##_error_t;                                                  \
static char * pto_node_name##_error_strings[] = {                              \
        #pto_node_name  " error processed packets"                             \
};      \
VLIB_REGISTER_NODE(pto_node_name##_node) = {                  \
    .name = #pto_node_name,                         \
    .vector_size = sizeof(u32),                     \
    .format_trace = format_##pto_node_name##_trace,       \
    .type = VLIB_NODE_TYPE_INTERNAL,                        \
    .n_errors = ARRAY_LEN(pto_node_name##_error_strings),   \
    .error_strings = pto_node_name##_error_strings,       \
    .n_next_nodes = 1,                                    \
    .next_nodes = {[CHAIN_NEXT_NODE] = #pto_next_node_name},    \
};  \
VLIB_NODE_FN(pto_node_name##_node)                 \
(vlib_main_t *vm, vlib_node_runtime_t *node, vlib_frame_t *frame) {   \
  u32 n_left_from, *from, *to_next;                     \
  protocol_next_t next_index;             \
  u32 pkts_processed = 0;                 \
                                              \
  from = vlib_frame_vector_args(frame);         \
  n_left_from = frame->n_vectors;           \
  next_index = node->cached_next_index;       \
                                                  \
  while (n_left_from > 0) {                 \
    u32 n_left_to_next;         \
    vlib_get_next_frame(vm, node, next_index, to_next, n_left_to_next);     \
    while (n_left_from >= 4 && n_left_to_next >= 2) {     \
      u32 next0 = CHAIN_NEXT_NODE;                      \
      u32 next1 = CHAIN_NEXT_NODE;                      \
      u32 bi0, bi1;                                     \
      vlib_buffer_t *b0, *b1;                           \
      {                                                 \
        vlib_buffer_t *p2, *p3;                         \
        p2 = vlib_get_buffer(vm, from[2]);                \
        p3 = vlib_get_buffer(vm, from[3]);                    \
        vlib_prefetch_buffer_header(p2, LOAD);                \
        vlib_prefetch_buffer_header(p3, LOAD);                \
        CLIB_PREFETCH(p2->data, CLIB_CACHE_LINE_BYTES, STORE);  \
        CLIB_PREFETCH(p3->data, CLIB_CACHE_LINE_BYTES, STORE);    \
      }                                                             \
      to_next[0] = bi0 = from[0];                       \
      to_next[1] = bi1 = from[1];                       \
      from += 2;                                        \
      to_next += 2;                                     \
      n_left_from -= 2;                                 \
      n_left_to_next -= 2;                                \
      b0 = vlib_get_buffer(vm, bi0);                      \
      b1 = vlib_get_buffer(vm, bi1);                      \
      DUAL_PKT_PROCESS_FN(pto_node_name);                     \
      pkts_processed += 2;                                    \
      if (PREDICT_FALSE((node->flags & VLIB_NODE_FLAG_TRACE))) {    \
        if (b0->flags & VLIB_BUFFER_IS_TRACED) {                      \
          protocol_trace_t *t = vlib_add_trace(vm, node, b0, sizeof(*t));      \
          t->next_index = next0;                                                  \
          ip4_header_t *ip0 = vlib_buffer_get_current(b0);                        \
          clib_memcpy(t->src_ip, &ip0->src_address, sizeof(t->src_ip));           \
          clib_memcpy(t->dst_ip, &ip0->dst_address, sizeof(t->dst_ip));             \
          t->current_length = b0->current_length;                                   \
        }                           \
        if (b1->flags & VLIB_BUFFER_IS_TRACED) {                                      \
          protocol_trace_t *t = vlib_add_trace(vm, node, b1, sizeof(*t));    \
          t->next_index = next1;                                                    \
          ip4_header_t *ip1 = vlib_buffer_get_current(b1);                          \
          clib_memcpy(t->src_ip, &ip1->src_address, sizeof(t->src_ip));               \
          clib_memcpy(t->dst_ip, &ip1->dst_address, sizeof(t->dst_ip));               \
          t->current_length = b0->current_length;                             \
        }     \
      }         \
      vlib_validate_buffer_enqueue_x2(vm, node, next_index, to_next,                \
                                      n_left_to_next, bi0, bi1, next0, next1);        \
    }           \
    while (n_left_from > 0 && n_left_to_next > 0) {         \
      u32 bi0;                                  \
      vlib_buffer_t *b0;                        \
      u32 next0 = CHAIN_NEXT_NODE;              \
      bi0 = from[0];                          \
      to_next[0] = bi0;                       \
      from += 1;                              \
      to_next += 1;                         \
      n_left_from -= 1;                     \
      n_left_to_next -= 1;                  \
      b0 = vlib_get_buffer(vm, bi0);        \
      SINGLE_PKT_PROCESS_FN(pto_node_name);   \
      pkts_processed += 1;                    \
      if (PREDICT_FALSE((node->flags & VLIB_NODE_FLAG_TRACE))) {    \
        if (b0->flags & VLIB_BUFFER_IS_TRACED) {                  \
          protocol_trace_t *t = vlib_add_trace(vm, node, b0, sizeof(*t));      \
          t->next_index = next0;                                                      \
          ip4_header_t *ip0 = vlib_buffer_get_current(b0);                          \
          clib_memcpy(t->src_ip, &ip0->src_address, sizeof(t->src_ip));             \
          clib_memcpy(t->dst_ip, &ip0->dst_address, sizeof(t->dst_ip));             \
          t->current_length = b0->current_length;                                 \
        }               \
      }                 \
      vlib_validate_buffer_enqueue_x1(vm, node, next_index, to_next,                \
                                      n_left_to_next, bi0, next0);                \
    }             \
    vlib_put_next_frame(vm, node, next_index, n_left_to_next);              \
  }     \
  vlib_node_increment_counter(vm, pto_node_name##_node.index,                       \
                              pto_node_name##_PROCESSED, pkts_processed);           \
  return frame->n_vectors;        \
}                                 

#endif