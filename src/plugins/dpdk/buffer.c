/*
 * Copyright (c) 2017-2019 Cisco and/or its affiliates.
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at:
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#include <unistd.h>
#include <errno.h>
#include <rte_config.h>
#include <rte_ethdev.h>
#include <rte_cryptodev.h>
#include <rte_vfio.h>
#include <rte_version.h>
#include <rte_mbuf.h>

#include <vlib/vlib.h>
#include <dpdk/buffer.h>

STATIC_ASSERT (VLIB_BUFFER_PRE_DATA_SIZE == RTE_PKTMBUF_HEADROOM,
	       "VLIB_BUFFER_PRE_DATA_SIZE must be equal to RTE_PKTMBUF_HEADROOM");

extern struct rte_mbuf *dpdk_mbuf_template_by_pool_index;
#ifndef CLIB_MARCH_VARIANT
struct rte_mempool **dpdk_mempool_by_buffer_pool_index = 0;
struct rte_mempool **dpdk_no_cache_mempool_by_buffer_pool_index = 0;
struct rte_mbuf *dpdk_mbuf_template_by_pool_index = 0;

u8 **pcap_packets;
u32 pcap_pkt_count = 0;

static const char *PCAP_PATH = "/mnt/disk1/yangbin/CODING/WorkSpace/vpp/"
			       "vpp-hw/exps/huawei_exp/pkts_wo_io.pcap";

#define _PCAP_MAGIC_NUMBER  0xa1b2c3d4
#define _PCAP_MAJOR_VERSION 2
#define _PCAP_MINOR_VERSION 4

typedef struct
{
  uint32_t magic_number;  /**< magic number */
  uint16_t version_major; /**< major version number */
  uint16_t version_minor; /**< minor version number */
  int32_t thiszone;	  /**< GMT to local correction */
  uint32_t sigfigs;	  /**< accuracy of timestamps */
  uint32_t snaplen;	  /**< max length of captured packets, in octets */
  uint32_t network;	  /**< data link type */
} __pcap_hdr_t;

typedef struct
{
  uint32_t ts_sec;   /**< timestamp seconds */
  uint32_t ts_usec;  /**< timestamp microseconds */
  uint32_t incl_len; /**< number of octets of packet saved in file */
  uint32_t orig_len; /**< actual length of packet */
} __pcap_record_hdr_t;

typedef struct
{
  char *filename;	  /**< allocated string for filename of pcap */
  FILE *fp;		  /**< file pointer for pcap file */
  struct rte_mempool *mp; /**< Mempool for storing packets */
  uint32_t
    convert; /**< Endian flag value if 1 convert to host endian format */
  uint32_t max_pkt_size; /**< largest packet found in pcap file */
  uint32_t pkt_count;	 /**< Number of packets in pcap file */
  uint32_t pkt_index;	 /**< Index of current packet in pcap file */
  __pcap_hdr_t info;	 /**< information on the PCAP file */
  int32_t pcap_result;	 /**< PCAP result of filter compile */
  vlib_buffer_template_t buffer_template;
} __pcap_info_t;

static_always_inline void
__pcap_convert (__pcap_info_t *pcap, __pcap_record_hdr_t *pHdr)
{
  if (pcap->convert)
    {
      pHdr->incl_len = ntohl (pHdr->incl_len);
      pHdr->orig_len = ntohl (pHdr->orig_len);
      pHdr->ts_sec = ntohl (pHdr->ts_sec);
      pHdr->ts_usec = ntohl (pHdr->ts_usec);
    }
}

static_always_inline void
__pcap_rewind (__pcap_info_t *pcap)
{
  /* Rewind to the beginning */
  rewind (pcap->fp);

  /* Seek past the pcap header */
  (void) fseek (pcap->fp, sizeof (__pcap_hdr_t), SEEK_SET);
}

static_always_inline clib_error_t *
__pcap_get_info (__pcap_info_t *pcap)
{
  __pcap_record_hdr_t hdr;

  if (fread (&pcap->info, 1, sizeof (__pcap_hdr_t), pcap->fp) !=
      sizeof (__pcap_hdr_t))
    return clib_error_return (0, "%s: failed to read pcap header", __func__);

  /* Make sure we have a valid PCAP file for Big or Little Endian formats. */
  if (pcap->info.magic_number == _PCAP_MAGIC_NUMBER)
    pcap->convert = 0;
  else if (pcap->info.magic_number == ntohl (_PCAP_MAGIC_NUMBER))
    pcap->convert = 1;
  else
    return clib_error_return (0, "%s: invalid magic number 0x%08x", __func__,
			      pcap->info.magic_number);

  if (pcap->convert)
    {
      pcap->info.magic_number = ntohl (pcap->info.magic_number);
      pcap->info.version_major = ntohs (pcap->info.version_major);
      pcap->info.version_minor = ntohs (pcap->info.version_minor);
      pcap->info.thiszone = ntohl (pcap->info.thiszone);
      pcap->info.sigfigs = ntohl (pcap->info.sigfigs);
      pcap->info.snaplen = ntohl (pcap->info.snaplen);
      pcap->info.network = ntohl (pcap->info.network);
    }

  pcap->max_pkt_size = 0;
  /* count the number of packets and get the largest size packet */
  for (;;)
    {
      if (fread (&hdr, 1, sizeof (__pcap_record_hdr_t), pcap->fp) !=
	  sizeof (hdr))
	break;

      /* Convert the packet header to the correct format if needed */
      __pcap_convert (pcap, &hdr);

      if (fseek (pcap->fp, hdr.incl_len, SEEK_CUR) < 0)
	break;

      pcap->pkt_count++;
      if (hdr.incl_len > pcap->max_pkt_size)
	pcap->max_pkt_size = hdr.incl_len;
    }
  pcap->max_pkt_size += RTE_PKTMBUF_HEADROOM;
  pcap->max_pkt_size =
    RTE_ALIGN_CEIL (pcap->max_pkt_size, RTE_CACHE_LINE_SIZE);
  printf ("PCAP: Max Packet Size: %d\n", pcap->max_pkt_size);

  __pcap_rewind (pcap);

  return 0;
}

static_always_inline clib_error_t *
dpdk_buffer_pool_load_pcap(vlib_main_t *vm, vlib_buffer_pool_t * bp, __pcap_info_t* pcap)
{
  uword buffer_mem_start = vm->buffer_main->buffer_mem_start;
  u32 pkt_count, i;
  pkt_count = pcap->pkt_count;

  if (bp->n_buffers < pkt_count)
    {
      clib_warning("buffer pool buffer size < pcap pkt count");
      pkt_count = bp->n_buffers;
    }
  
  if (!pcap_pkt_count) 
    {
	pcap_pkt_count = pkt_count;
    }
  else if (pcap_pkt_count != pkt_count) 
    {
        return clib_error_return (0, "%s: failed to read pcap to pool, pkt_count not equals\n", __func__);
    }

  /* populate buffers with pcap*/
  for (i = 0; i < pkt_count; i++)
    {
      vlib_buffer_t *b = vlib_buffer_ptr_from_index (buffer_mem_start, bp->buffers[i], 0);
      clib_warning("#########populate buffer %d, buffer num %d, pool_index %d ########", i, bp->n_buffers, b->buffer_pool_index);
      b = vlib_get_buffer (vm, bp->buffers[i]);
      struct rte_mbuf *mb = rte_mbuf_from_vlib_buffer(b);
      __pcap_record_hdr_t hdr = { 0 };

      if (fread (&hdr, 1, sizeof (__pcap_record_hdr_t), pcap->fp) != sizeof (hdr))
        {
          __pcap_rewind (pcap);
          if (fread (&hdr, 1, sizeof (__pcap_record_hdr_t), pcap->fp) != sizeof (hdr))
	    return clib_error_return (0, "%s: failed to read pcap header\n", __func__);
        }

      /* Convert the packet header to the correct format. */
      __pcap_convert (pcap, &hdr);
      if (hdr.incl_len > bp->data_size) 
        return clib_error_return (0, "%s: failed to read packet data from PCAP file, pkts is too large\n", __func__);
      
      clib_warning("######## rte data off %d, pkt_len %d, buffer data_size %d###########", mb->data_off, hdr.incl_len, bp->data_size);
      if (fread (rte_pktmbuf_mtod (mb, char *), 1, hdr.incl_len, pcap->fp) == 0)
        return clib_error_return (0, "%s: failed to read packet data from PCAP file\n", __func__);

      mb->next = NULL;
      mb->data_len = hdr.incl_len;
      mb->pkt_len = hdr.incl_len;
      mb->port = 0;
      mb->ol_flags = 0;
    }
    __pcap_rewind (pcap); 
    return 0;
}

clib_error_t *
dpdk_load_pcap (vlib_main_t * vm)
{
  clib_error_t *error = 0;
  vlib_buffer_pool_t *bp;
  __pcap_info_t pcap = { 0 };
  clib_error_t *err;
  u32 pkt_count;

  pcap.filename = (char *) PCAP_PATH;

  pcap.fp = fopen (pcap.filename, "r");
  if (!pcap.fp)
    return clib_error_return (0, "Failed to open file for (%s)",
			      pcap.filename);

  error = __pcap_get_info (&pcap);
  if (error)
    {
      fclose (pcap.fp);
      return error;
    }

  pkt_count = pcap.pkt_count;
  if (pkt_count == 0)
    {
      fclose (pcap.fp);
      return clib_error_return (0, "PCAP file is empty: %s", pcap.filename);
    }

  for (i = 0; i < pkt_count; i++)
    {
      __pcap_record_hdr_t hdr = { 0 };

      if (fread (&hdr, 1, sizeof (__pcap_record_hdr_t), pcap->fp) != sizeof (hdr))
        {
          __pcap_rewind (pcap);
          if (fread (&hdr, 1, sizeof (__pcap_record_hdr_t), pcap->fp) != sizeof (hdr))
	    return clib_error_return (0, "%s: failed to read pcap header\n", __func__);
        }

      /* Convert the packet header to the correct format. */
      __pcap_convert (pcap, &hdr);
      if (hdr.incl_len > bp->data_size) 
        return clib_error_return (0, "%s: failed to read packet data from PCAP file, pkts is too large\n", __func__);
      
      u8 *data = vec_new (u8, hdr.incl_len);

      clib_warning("######## rte data off %d, pkt_len %d, buffer data_size %d###########", mb->data_off, hdr.incl_len, bp->data_size);
      if (fread (data, 1, hdr.incl_len , pcap->fp) == 0)
        return clib_error_return (0, "%s: failed to read packet data from PCAP file\n", __func__);

      vec_add1 (pcap_packets, data);
    }
  fclose (pcap.fp);
  return 0;
}

clib_error_t *
dpdk_buffer_pool_init (vlib_main_t * vm, vlib_buffer_pool_t * bp)
{
  uword buffer_mem_start = vm->buffer_main->buffer_mem_start;
  struct rte_mempool *mp, *nmp;
  struct rte_pktmbuf_pool_private priv;
  enum rte_iova_mode iova_mode;
  u32 i;
  u8 *name = 0;

  u32 elt_size =
    sizeof (struct rte_mbuf) + sizeof (vlib_buffer_t) + bp->data_size;

  /* create empty mempools */
  vec_validate_aligned (dpdk_mempool_by_buffer_pool_index, bp->index,
			CLIB_CACHE_LINE_BYTES);
  vec_validate_aligned (dpdk_no_cache_mempool_by_buffer_pool_index, bp->index,
			CLIB_CACHE_LINE_BYTES);

  /* normal mempool */
  name = format (name, "vpp pool %u%c", bp->index, 0);
  mp = rte_mempool_create_empty ((char *) name, bp->n_buffers,
				 elt_size, 512, sizeof (priv),
				 bp->numa_node, 0);
  if (!mp)
    {
      vec_free (name);
      return clib_error_return (0,
				"failed to create normal mempool for numa node %u",
				bp->index);
    }
  vec_reset_length (name);

  /* non-cached mempool */
  name = format (name, "vpp pool %u (no cache)%c", bp->index, 0);
  nmp = rte_mempool_create_empty ((char *) name, bp->n_buffers,
				  elt_size, 0, sizeof (priv),
				  bp->numa_node, 0);
  if (!nmp)
    {
      rte_mempool_free (mp);
      vec_free (name);
      return clib_error_return (0,
				"failed to create non-cache mempool for numa nude %u",
				bp->index);
    }
  vec_free (name);

  dpdk_mempool_by_buffer_pool_index[bp->index] = mp;
  dpdk_no_cache_mempool_by_buffer_pool_index[bp->index] = nmp;

  mp->pool_id = nmp->pool_id = bp->index;

  rte_mempool_set_ops_byname (mp, "vpp", NULL);
  rte_mempool_set_ops_byname (nmp, "vpp-no-cache", NULL);

  /* Call the mempool priv initializer */
  memset (&priv, 0, sizeof (priv));
  priv.mbuf_data_room_size = VLIB_BUFFER_PRE_DATA_SIZE +
    vlib_buffer_get_default_data_size (vm);
  priv.mbuf_priv_size = VLIB_BUFFER_HDR_SIZE;
  rte_pktmbuf_pool_init (mp, &priv);
  rte_pktmbuf_pool_init (nmp, &priv);

  iova_mode = rte_eal_iova_mode ();

  /* populate mempool object buffer header */
  for (i = 0; i < bp->n_buffers; i++)
    {
      struct rte_mempool_objhdr *hdr;
      vlib_buffer_t *b = vlib_get_buffer (vm, bp->buffers[i]);
      struct rte_mbuf *mb = rte_mbuf_from_vlib_buffer (b);
      hdr = (struct rte_mempool_objhdr *) RTE_PTR_SUB (mb, sizeof (*hdr));
      hdr->mp = mp;
      hdr->iova = (iova_mode == RTE_IOVA_VA) ?
	pointer_to_uword (mb) : vlib_physmem_get_pa (vm, mb);
      STAILQ_INSERT_TAIL (&mp->elt_list, hdr, next);
      STAILQ_INSERT_TAIL (&nmp->elt_list, hdr, next);
      mp->populated_size++;
      nmp->populated_size++;
    }
#if RTE_VERSION >= RTE_VERSION_NUM(22, 3, 0, 0)
  mp->flags &= ~RTE_MEMPOOL_F_NON_IO;
#endif

  /* call the object initializers */
  rte_mempool_obj_iter (mp, rte_pktmbuf_init, 0);

  /* create mbuf header tempate from the first buffer in the pool */
  vec_validate_aligned (dpdk_mbuf_template_by_pool_index, bp->index,
			CLIB_CACHE_LINE_BYTES);
  clib_memcpy (vec_elt_at_index (dpdk_mbuf_template_by_pool_index, bp->index),
	       rte_mbuf_from_vlib_buffer (vlib_buffer_ptr_from_index
					  (buffer_mem_start, *bp->buffers,
					   0)), sizeof (struct rte_mbuf));

  for (i = 0; i < bp->n_buffers; i++)
    {
      vlib_buffer_t *b;
      b = vlib_buffer_ptr_from_index (buffer_mem_start, bp->buffers[i], 0);
      b->template = bp->buffer_template;
    }

  /* map DMA pages if at least one physical device exists */
  if (rte_eth_dev_count_avail () || rte_cryptodev_count ())
    {
      uword i;
      size_t page_sz;
      vlib_physmem_map_t *pm;
      int do_vfio_map = 1;

      pm = vlib_physmem_get_map (vm, bp->physmem_map_index);
      page_sz = 1ULL << pm->log2_page_size;

      for (i = 0; i < pm->n_pages; i++)
	{
	  char *va = ((char *) pm->base) + i * page_sz;
	  uword pa = (iova_mode == RTE_IOVA_VA) ?
	    pointer_to_uword (va) : pm->page_table[i];

	  if (do_vfio_map &&
#if RTE_VERSION < RTE_VERSION_NUM(19, 11, 0, 0)
	      rte_vfio_dma_map (pointer_to_uword (va), pa, page_sz))
#else
	      rte_vfio_container_dma_map (RTE_VFIO_DEFAULT_CONTAINER_FD,
					  pointer_to_uword (va), pa, page_sz))
#endif
	    do_vfio_map = 0;

	  struct rte_mempool_memhdr *memhdr;
	  memhdr = clib_mem_alloc (sizeof (*memhdr));
	  memhdr->mp = mp;
	  memhdr->addr = va;
	  memhdr->iova = pa;
	  memhdr->len = page_sz;
	  memhdr->free_cb = 0;
	  memhdr->opaque = 0;

	  STAILQ_INSERT_TAIL (&mp->mem_list, memhdr, next);
	  mp->nb_mem_chunks++;
	}
    }

  return 0;
}

static int
dpdk_ops_vpp_alloc (struct rte_mempool *mp)
{
  clib_warning ("");
  return 0;
}

static void
dpdk_ops_vpp_free (struct rte_mempool *mp)
{
  clib_warning ("");
}

#endif

static_always_inline void
dpdk_ops_vpp_enqueue_one (vlib_buffer_template_t *bt, void *obj)
{
  /* Only non-replicated packets (b->ref_count == 1) expected */

  struct rte_mbuf *mb = obj;
  vlib_buffer_t *b = vlib_buffer_from_rte_mbuf (mb);
  ASSERT (b->ref_count == 1);
  ASSERT (b->buffer_pool_index == bt->buffer_pool_index);
  b->template = *bt;
}

int
CLIB_MULTIARCH_FN (dpdk_ops_vpp_enqueue) (struct rte_mempool * mp,
					  void *const *obj_table, unsigned n)
{
  const int batch_size = 32;
  vlib_main_t *vm = vlib_get_main ();
  vlib_buffer_template_t bt;
  u8 buffer_pool_index = mp->pool_id;
  vlib_buffer_pool_t *bp = vlib_get_buffer_pool (vm, buffer_pool_index);
  u32 bufs[batch_size];
  u32 n_left = n;
  void *const *obj = obj_table;

  bt = bp->buffer_template;

  while (n_left >= 4)
    {
      dpdk_ops_vpp_enqueue_one (&bt, obj[0]);
      dpdk_ops_vpp_enqueue_one (&bt, obj[1]);
      dpdk_ops_vpp_enqueue_one (&bt, obj[2]);
      dpdk_ops_vpp_enqueue_one (&bt, obj[3]);
      obj += 4;
      n_left -= 4;
    }

  while (n_left)
    {
      dpdk_ops_vpp_enqueue_one (&bt, obj[0]);
      obj += 1;
      n_left -= 1;
    }

  while (n >= batch_size)
    {
      vlib_get_buffer_indices_with_offset (vm, (void **) obj_table, bufs,
					   batch_size,
					   sizeof (struct rte_mbuf));
      vlib_buffer_pool_put (vm, buffer_pool_index, bufs, batch_size);
      n -= batch_size;
      obj_table += batch_size;
    }

  if (n)
    {
      vlib_get_buffer_indices_with_offset (vm, (void **) obj_table, bufs,
					   n, sizeof (struct rte_mbuf));
      vlib_buffer_pool_put (vm, buffer_pool_index, bufs, n);
    }

  return 0;
}

CLIB_MARCH_FN_REGISTRATION (dpdk_ops_vpp_enqueue);

static_always_inline void
dpdk_ops_vpp_enqueue_no_cache_one (vlib_main_t *vm, struct rte_mempool *old,
				   struct rte_mempool *new, void *obj,
				   vlib_buffer_template_t *bt)
{
  struct rte_mbuf *mb = obj;
  vlib_buffer_t *b = vlib_buffer_from_rte_mbuf (mb);

  if (clib_atomic_sub_fetch (&b->ref_count, 1) == 0)
    {
      u32 bi = vlib_get_buffer_index (vm, b);
      b->template = *bt;
      vlib_buffer_pool_put (vm, bt->buffer_pool_index, &bi, 1);
      return;
    }
}

int
CLIB_MULTIARCH_FN (dpdk_ops_vpp_enqueue_no_cache) (struct rte_mempool * cmp,
						   void *const *obj_table,
						   unsigned n)
{
  vlib_main_t *vm = vlib_get_main ();
  vlib_buffer_template_t bt;
  struct rte_mempool *mp;
  mp = dpdk_mempool_by_buffer_pool_index[cmp->pool_id];
  u8 buffer_pool_index = cmp->pool_id;
  vlib_buffer_pool_t *bp = vlib_get_buffer_pool (vm, buffer_pool_index);
  bt = bp->buffer_template;

  while (n >= 4)
    {
      dpdk_ops_vpp_enqueue_no_cache_one (vm, cmp, mp, obj_table[0], &bt);
      dpdk_ops_vpp_enqueue_no_cache_one (vm, cmp, mp, obj_table[1], &bt);
      dpdk_ops_vpp_enqueue_no_cache_one (vm, cmp, mp, obj_table[2], &bt);
      dpdk_ops_vpp_enqueue_no_cache_one (vm, cmp, mp, obj_table[3], &bt);
      obj_table += 4;
      n -= 4;
    }

  while (n)
    {
      dpdk_ops_vpp_enqueue_no_cache_one (vm, cmp, mp, obj_table[0], &bt);
      obj_table += 1;
      n -= 1;
    }

  return 0;
}

CLIB_MARCH_FN_REGISTRATION (dpdk_ops_vpp_enqueue_no_cache);

static_always_inline void
dpdk_mbuf_init_from_template (struct rte_mbuf **mba, struct rte_mbuf *mt,
			      int count)
{
  /* Assumptions about rte_mbuf layout */
  STATIC_ASSERT_OFFSET_OF (struct rte_mbuf, buf_addr, 0);
  STATIC_ASSERT_OFFSET_OF (struct rte_mbuf, buf_iova, 8);
  STATIC_ASSERT_SIZEOF_ELT (struct rte_mbuf, buf_iova, 8);
  STATIC_ASSERT_SIZEOF_ELT (struct rte_mbuf, buf_iova, 8);
  STATIC_ASSERT_SIZEOF (struct rte_mbuf, 128);

  while (count--)
    {
      struct rte_mbuf *mb = mba[0];
      int i;
      /* bytes 0 .. 15 hold buf_addr and buf_iova which we need to preserve */
      /* copy bytes 16 .. 31 */
      *((u8x16 *) mb + 1) = *((u8x16 *) mt + 1);

      /* copy bytes 32 .. 127 */
#ifdef CLIB_HAVE_VEC256
      for (i = 1; i < 4; i++)
	*((u8x32 *) mb + i) = *((u8x32 *) mt + i);
#else
      for (i = 2; i < 8; i++)
	*((u8x16 *) mb + i) = *((u8x16 *) mt + i);
#endif
      mba++;
    }
}

int
CLIB_MULTIARCH_FN (dpdk_ops_vpp_dequeue) (struct rte_mempool * mp,
					  void **obj_table, unsigned n)
{
  const int batch_size = 32;
  vlib_main_t *vm = vlib_get_main ();
  u32 bufs[batch_size], total = 0, n_alloc = 0;
  u8 buffer_pool_index = mp->pool_id;
  void **obj = obj_table;
  struct rte_mbuf t = dpdk_mbuf_template_by_pool_index[buffer_pool_index];

  while (n >= batch_size)
    {
      n_alloc = vlib_buffer_alloc_from_pool (vm, bufs, batch_size,
					     buffer_pool_index);
      if (n_alloc != batch_size)
	goto alloc_fail;

      vlib_get_buffers_with_offset (vm, bufs, obj, batch_size,
				    -(i32) sizeof (struct rte_mbuf));
      dpdk_mbuf_init_from_template ((struct rte_mbuf **) obj, &t, batch_size);
      total += batch_size;
      obj += batch_size;
      n -= batch_size;
    }

  if (n)
    {
      n_alloc = vlib_buffer_alloc_from_pool (vm, bufs, n, buffer_pool_index);

      if (n_alloc != n)
	goto alloc_fail;

      vlib_get_buffers_with_offset (vm, bufs, obj, n,
				    -(i32) sizeof (struct rte_mbuf));
      dpdk_mbuf_init_from_template ((struct rte_mbuf **) obj, &t, n);
    }

  return 0;

alloc_fail:
  /* dpdk doesn't support partial alloc, so we need to return what we
     already got */
  if (n_alloc)
    vlib_buffer_pool_put (vm, buffer_pool_index, bufs, n_alloc);
  obj = obj_table;
  while (total)
    {
      vlib_get_buffer_indices_with_offset (vm, obj, bufs, batch_size,
					   sizeof (struct rte_mbuf));
      vlib_buffer_pool_put (vm, buffer_pool_index, bufs, batch_size);

      obj += batch_size;
      total -= batch_size;
    }
  return -ENOENT;
}

CLIB_MARCH_FN_REGISTRATION (dpdk_ops_vpp_dequeue);

#ifndef CLIB_MARCH_VARIANT

static int
dpdk_ops_vpp_dequeue_no_cache (struct rte_mempool *mp, void **obj_table,
			       unsigned n)
{
  clib_error ("bug");
  return 0;
}

static unsigned
dpdk_ops_vpp_get_count (const struct rte_mempool *mp)
{
  vlib_main_t *vm = vlib_get_main ();
  if (mp)
    {
      vlib_buffer_pool_t *pool = vlib_get_buffer_pool (vm, mp->pool_id);
      if (pool)
	{
	  return pool->n_avail;
	}
    }
  return 0;
}

static unsigned
dpdk_ops_vpp_get_count_no_cache (const struct rte_mempool *mp)
{
  struct rte_mempool *cmp;
  cmp = dpdk_no_cache_mempool_by_buffer_pool_index[mp->pool_id];
  return dpdk_ops_vpp_get_count (cmp);
}

clib_error_t *
dpdk_buffer_pools_create (vlib_main_t * vm)
{
  clib_error_t *err;
  vlib_buffer_pool_t *bp;

  struct rte_mempool_ops ops = { };

  strncpy (ops.name, "vpp", 4);
  ops.alloc = dpdk_ops_vpp_alloc;
  ops.free = dpdk_ops_vpp_free;
  ops.get_count = dpdk_ops_vpp_get_count;
  ops.enqueue = CLIB_MARCH_FN_POINTER (dpdk_ops_vpp_enqueue);
  ops.dequeue = CLIB_MARCH_FN_POINTER (dpdk_ops_vpp_dequeue);
  rte_mempool_register_ops (&ops);

  strncpy (ops.name, "vpp-no-cache", 13);
  ops.get_count = dpdk_ops_vpp_get_count_no_cache;
  ops.enqueue = CLIB_MARCH_FN_POINTER (dpdk_ops_vpp_enqueue_no_cache);
  ops.dequeue = dpdk_ops_vpp_dequeue_no_cache;
  rte_mempool_register_ops (&ops);

  /* *INDENT-OFF* */
  vec_foreach (bp, vm->buffer_main->buffer_pools)
    if (bp->start && (err = dpdk_buffer_pool_init (vm, bp)))
      return err;
  /* *INDENT-ON* */
  return 0;
}

VLIB_BUFFER_SET_EXT_HDR_SIZE (sizeof (struct rte_mempool_objhdr) +
			      sizeof (struct rte_mbuf));

#endif

/** @endcond */
/*
 * fd.io coding-style-patch-verification: ON
 *
 * Local Variables:
 * eval: (c-set-style "gnu")
 * End:
 */
