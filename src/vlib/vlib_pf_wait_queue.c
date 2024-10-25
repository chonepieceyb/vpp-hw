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

void
process_expired_pf_cb (u32 *expired_timer_handles)
{
  vlib_main_t *vm = vlib_get_main ();
  vlib_node_main_t *nm = &vm->node_main;
  u32 *handle;

  vec_foreach (handle, expired_timer_handles)
    {
      u32 pfi = *handle; 
      vlib_pending_frame_t *pf = pool_elt_at_index(nm->pending_frames, pfi);
      if (pf->next_frame_index != VLIB_PENDING_FRAME_NO_NEXT_FRAME)
        {
          vlib_next_frame_t *nf = vec_elt_at_index (nm->next_frames, pf->next_frame_index);
          nf->stop_timer_handler = ~0;
          //clib_warning("++++++++++++vpp timeouts+++++++++++,  pf index %lu, node runtime index %lu,  time %.6f ++++++++++++++,", pfi, pf->node_runtime_index, vlib_time_now(vm));
        }
      pf->is_timeout = 1;
    }
  vec_append (nm->pf_runq, expired_timer_handles);
}