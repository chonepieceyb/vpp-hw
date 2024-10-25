/*
 * author: chonepieceyb
 */


#ifndef __included_vlib_pf_wait_queue_h__
#define __included_vlib_pf_wait_queue_h__

/* ... So that a client app can create multiple wheel geometries */
#undef TW_TIMER_WHEELS
#undef TW_SLOTS_PER_RING
#undef TW_RING_SHIFT
#undef TW_RING_MASK
#undef TW_TIMERS_PER_OBJECT
#undef LOG2_TW_TIMERS_PER_OBJECT
#undef TW_SUFFIX
#undef TW_OVERFLOW_VECTOR
#undef TW_FAST_WHEEL_BITMAP
#undef TW_TIMER_ALLOW_DUPLICATE_STOP
#undef TW_START_STOP_TRACE_SIZE

#define TW_TIMER_WHEELS 1
#define TW_SLOTS_PER_RING 1024
#define TW_RING_SHIFT 10
#define TW_RING_MASK (TW_SLOTS_PER_RING -1)
#define TW_TIMERS_PER_OBJECT 1
#define LOG2_TW_TIMERS_PER_OBJECT 0
#define TW_SUFFIX _pf_waitq
#define TW_FAST_WHEEL_BITMAP 0
#define TW_TIMER_ALLOW_DUPLICATE_STOP 0

#include <vppinfra/tw_timer_template.h>

void process_expired_pf_cb (u32 *expired_timer_handles);

#endif