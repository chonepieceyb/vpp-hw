#include "pcap_mempool.h"

#include <vlib/vlib.h>

#include <rte_errno.h>
#include <rte_mbuf.h>

static __inline__ void
mbuf_iterate_cb (struct rte_mempool *mp, void *opaque, void *obj,
		 unsigned obj_idx)
{
  pcap_mempool_main_t *pm = (pcap_mempool_main_t *) opaque;
  struct rte_mbuf *m = (struct rte_mbuf *) obj;
  u8 *data = vec_elt (pm->pcap.packets_read, obj_idx);
  u32 data_len = vec_len (data);

  clib_memcpy (rte_pktmbuf_mtod (m, u8 *), data, data_len);

  m->pool = mp;
  m->next = NULL;
  m->data_len = data_len;
  m->pkt_len = data_len;
  m->port = 0;
  m->ol_flags = 0;
}

clib_error_t *
pcap_mempool_open (pcap_mempool_main_t *pm, u8 *filename)
{
  clib_error_t *error = 0;
  struct rte_mempool *mp;

  if (!pm)
    {
      error = clib_error_return (0, "pm is NULL");
      goto out;
    }

  if (pm->pcap.file_name)
    {
      error = clib_error_return (0, "pcap file name is already set");
      goto out;
    }
  pm->pcap.file_name = (char *) format (filename, "%c", 0);

  error = pcap_read (&pm->pcap);
  if (error)
    {
      error =
	clib_error_return (0, "pcap_read error: %U", format_clib_error, error);
      goto out_free_file_name;
    }

  /* TODO: Revisit name, cache_size, priv_size, socket_id */
  mp = rte_pktmbuf_pool_create ("vpp-pcap", pm->pcap.n_packets_captured, 0, 0,
				pm->pcap.max_packet_bytes, 0);
  if (!mp)
    {
      error = clib_error_return (
	0, "Cannot create mbuf pool (%s) nb_mbufs %d, socket_id %d: %s",
	"vpp-pcap", pm->pcap.n_packets_captured, 0, rte_strerror (rte_errno));
      goto out_close_pcap;
    }

  rte_mempool_obj_iter (mp, mbuf_iterate_cb, pm);
  pm->mp = mp;

  goto out;

out_close_pcap:
  pcap_close (&pm->pcap);
out_free_file_name:
  vec_free (pm->pcap.file_name);
out:
  return error;
}

clib_error_t *
pcap_mempool_close (pcap_mempool_main_t *pm)
{
  clib_error_t *error = 0;

  if (!pm)
    {
      error = clib_error_return (0, "pm is NULL");
      goto out;
    }

  if (pm->mp)
    rte_mempool_free (pm->mp);

  pcap_close (&pm->pcap);

  if (pm->pcap.file_name)
    vec_free (pm->pcap.file_name);

out:
  return error;
}
