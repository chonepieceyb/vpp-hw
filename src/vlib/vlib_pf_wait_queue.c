/*
 * author: chonepieceyb
 */

#include <vlib/vlib.h>
#include <vlib/node.h>
#include <vppinfra/pool.h>
#include <vppinfra/vec.h>
#include <vlib/main.h>
#include <vppinfra/error.h>
#include <vlib/node_funcs.h>
#include <vlib/vlib_pf_wait_queue.h>
#include <vppinfra/tw_timer_template.c>
#include <vlib/vlib_pf_run_queue.h>
#include <vlib/vlib_edf_timestamp.h>

void
process_expired_pf_cb (u32 *expired_timer_handles)
{
  vlib_main_t *vm = vlib_get_main ();
  vlib_node_main_t *nm = &vm->node_main;
  u32 *handle, *elt;

  vec_foreach (handle, expired_timer_handles)
    {
      u32 pfi = *handle; 
      vlib_pending_frame_t *pf = pool_elt_at_index(nm->pending_frames, pfi);
      u64 max_deadline_ts = calculate_max_deadline_ts(vm, pf);
      pf->timeout_deadline_ts = max_deadline_ts;

      if (pf->next_frame_index != VLIB_PENDING_FRAME_NO_NEXT_FRAME)
        {
          vlib_next_frame_t *nf = vec_elt_at_index (nm->next_frames, pf->next_frame_index);
          nf->stop_timer_handler = ~0;
          //clib_warning("++++++++++++vpp timeouts+++++++++++,  pf index %lu, node runtime index %lu,  time %.6f ++++++++++++++,", pfi, pf->node_runtime_index, vlib_time_now(vm));
        }
      pf->is_timeout = 1;

      elt = vlib_node_main_pf_runq_enqueue (nm, max_deadline_ts);
      if (elt)
	{
	  *elt = pfi;
	}
      else
	{
	  /* Run queue is full, invoke early rejection */
	  barrier_flush_all_pending_frames (vm);

#if VLIB_NODE_MAIN_PF_RUNQ_TRACE
	  ELOG_TYPE_DECLARE (e) = {
	    .format = "process_expired_pf_cb: early rejection %d",
	    .format_args = "i8",
	  };

	  struct
	  {
	    u64 early_rejection_count;
	  } *ed;
	  ed = ELOG_DATA (vlib_get_elog_main (), e);
	  ed->early_rejection_count += 1;
#endif
	}
    }
}