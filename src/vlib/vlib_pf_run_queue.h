#include "vppinfra/clib.h"
#include "vppinfra/string.h"
#include <vppinfra/vec.h>

typedef struct
{
  u32 ring_size; 
  u32 elt_bytes;
  u64 prod, cons;
} vlib_pf_runq_header_t;

always_inline vlib_pf_runq_header_t *
pf_runq_header (void *ring)
{
  return vec_header (ring);
}

always_inline void pf_runq_reset(void *ring, u32 ring_size, u32 elt_bytes)
{
  vlib_pf_runq_header_t *header = pf_runq_header (ring);
  header->ring_size = ring_size;
  header->elt_bytes = elt_bytes;
  header->cons = 0;
  header->prod = 0;
}

always_inline int __vlib_pf_runq_full(vlib_pf_runq_header_t *header)    
{                            
  return header->prod - header->cons == header->ring_size;                            
}   

always_inline int __vlib_pf_runq_empty(vlib_pf_runq_header_t *header)         
{                                                                                               
  return header->prod == header->cons;                                                        
}

always_inline void* __vlib_pf_runq_cons(void *ring)   
{                         
  vlib_pf_runq_header_t *header = pf_runq_header (ring);                                                      
  if (PREDICT_FALSE(__vlib_pf_runq_empty(header))) {                         
    return NULL;   /*ringbuf is empty*/                              
  } else {
    return ring + ((header->cons++) & (header->ring_size - 1)) * header->elt_bytes; 
  }                                                                        
}             
                                                                   
always_inline void* __vlib_pf_runq_prod(void *ring) 
{       
  vlib_pf_runq_header_t *header = pf_runq_header (ring);                                                                   
  if (PREDICT_FALSE(__vlib_pf_runq_full(header))) {                         
    return NULL;   /*ringbuf is full*/                              
  } else { 
    void *elt_prod = ring + ((header->prod) & (header->ring_size - 1)) * header->elt_bytes;                                                     
    if (PREDICT_FALSE(header->prod == ~0)) {
        clib_warning("pf_runq prod grow too fast!");
        header->cons &= (header->ring_size - 1);
        header->prod &= (header->ring_size - 1);
        header->prod += 1;
    } else {
        header->prod += 1;
    }
    return elt_prod;
  }                                                                        
}

always_inline void
__pf_runq_new_inline (void **p, u32 elt_bytes, u32 size, u32 align)
{
  void *ring;
  vec_attr_t va = { .elt_sz = elt_bytes,
		    .hdr_sz = sizeof (vlib_pf_runq_header_t),
		    .align = align };

  ring = _vec_alloc_internal (size, &va);
  pf_runq_reset(ring, size, elt_bytes);
  p[0] = ring;
}

always_inline u32 __vlib_pf_runq_len(void *ring)         
{                       
  vlib_pf_runq_header_t *header = pf_runq_header(ring);                                                                
  return header->prod - header->cons;                                                        
} 

#define pf_runq_new_aligned(ring, size_shift, align) \
{ __pf_runq_new_inline ((void **)&(ring), sizeof((ring)[0]), (1 << (size_shift)), align); }

#define pf_runq_new(ring, size_shift) \
{ __pf_runq_new_inline ((void **)&(ring), sizeof((ring)[0]), (1 << (size_shift)), 0);}

#define pf_runq_free(f) vec_free ((f))

#define pf_runq_deq(ring) \
__vlib_pf_runq_cons (ring)

#define pf_runq_try_enq(ring) \
__vlib_pf_runq_prod (ring)

#define pf_runq_len(ring) \
__vlib_pf_runq_len(ring)

always_inline void
__pf_runq_realloc (void **p)
{
  /*previous ring is too small*/
  void *old_ring = *p;
  void *old_elt, *new_elt;
  vlib_pf_runq_header_t *old_header = pf_runq_header (old_ring);
  u32 elt_bytes = old_header->elt_bytes;
  u32 ring_size = old_header->ring_size * 2;  //alloc a larger ring
  void *new_ring; 
  __pf_runq_new_inline (&new_ring, elt_bytes, ring_size, vec_get_align(old_ring));
  while ((old_elt = pf_runq_deq(old_ring)) != 0) {
    new_elt = pf_runq_try_enq(new_ring);
    ASSERT(new_elt != NULL && "failed to realloc pf runq");
    clib_memcpy_fast(new_elt, old_elt, elt_bytes);
  }
  pf_runq_free(old_ring);
  clib_warning("#### pf runq realloc success, current size %d, current len %d####", ring_size, pf_runq_len(new_ring));
  p[0] = new_ring;
}

always_inline void* __pf_runq_enqueue(void **ring_p)
{
    void *elt = pf_runq_try_enq(*ring_p);
    if (PREDICT_TRUE(elt != 0)) {
       return elt;
    }
    __pf_runq_realloc(ring_p);
    elt = pf_runq_try_enq(*ring_p);
    ASSERT(elt != 0 && "pf_runq realloc, but elt still is NULL");
    clib_warning("#### pf enqueue and realloc! current len %d######", pf_runq_len(*ring_p));
    return elt;
}

#define pf_runq_enq(ring) \
__pf_runq_enqueue ((void**)(&(ring)))