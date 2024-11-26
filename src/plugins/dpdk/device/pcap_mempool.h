#ifndef __included_pcap_mempool_h__
#define __included_pcap_mempool_h__

#include <vppinfra/pcap.h>
#include <vppinfra/pcap_funcs.h>

typedef struct pcap_mempool_main_t
{
  pcap_main_t pcap;
  struct rte_mempool *mp;
} pcap_mempool_main_t;

clib_error_t *pcap_mempool_open (pcap_mempool_main_t *pm, u8 *filename);

clib_error_t *pcap_mempool_close (pcap_mempool_main_t *pm);

#endif /* __included_pcap_mempool_h__ */
