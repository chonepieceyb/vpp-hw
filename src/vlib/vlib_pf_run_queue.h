#include "vppinfra/clib.h"
#include "vppinfra/string.h"
#include "vppinfra/types.h"
#include <vppinfra/vec.h>

#define PF_RUNQ_TYPE 0
typedef struct
{
  u32 ring_size; 
  u32 elt_bytes;
  u64 prod, cons;
} vlib_pf_runq_ring_header_t;


#define pf_runq_header(vec, type)   \
({                                  \
   vlib_pf_runq_##type##_header_t *__header;        \
   __header = (typeof(__header))vec_header ((vec));     \
})

always_inline void pf_runq_ring_reset(void *vec, u32 ring_size, u32 elt_bytes) {
  vlib_pf_runq_ring_header_t *header = pf_runq_header(vec, ring);
  header->ring_size = ring_size;
  header->elt_bytes = elt_bytes;
  header->cons = 0;
  header->prod = 0;
}

always_inline int __vlib_pf_runq_ring_full(vlib_pf_runq_ring_header_t *header) {
  return header->prod - header->cons == header->ring_size;
}

always_inline int
__vlib_pf_runq_ring_empty(vlib_pf_runq_ring_header_t *header) {
  return header->prod == header->cons;
}

always_inline void *__vlib_pf_runq_ring_cons(void *vec) {
  vlib_pf_runq_ring_header_t *header = pf_runq_header(vec, ring);
  if (PREDICT_FALSE(__vlib_pf_runq_ring_empty(header))) {
    return NULL;   /*ringbuf is empty*/
  } else {
    return vec +
           ((header->cons++) & (header->ring_size - 1)) * header->elt_bytes;
  }
}

always_inline void *____vlib_pf_runq_ring_prod(vlib_pf_runq_ring_header_t *header, void *vec) {
  void *elt_prod = vec + ((header->prod) & (header->ring_size - 1)) * header->elt_bytes;                                                     
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

always_inline void *__vlib_pf_runq_ring_prod(void *vec) {
  vlib_pf_runq_ring_header_t *header = pf_runq_header(vec, ring);
  if (PREDICT_FALSE(__vlib_pf_runq_ring_full(header))) {
    return NULL;   /*ringbuf is full*/
  } else {
    return ____vlib_pf_runq_ring_prod(header, vec);
  }
}

always_inline void
__pf_runq_ring_new_inline (void **p, u32 elt_bytes, u32 size, u32 align)
{
  void *ring;
  vec_attr_t va = {.elt_sz = elt_bytes,
                   .hdr_sz = sizeof(vlib_pf_runq_ring_header_t),
                   .align = align};

  ring = _vec_alloc_internal (size, &va);
  pf_runq_ring_reset(ring, size, elt_bytes);
  p[0] = ring;
}

always_inline u32 __vlib_pf_runq_ring_len(void *vec) {
  vlib_pf_runq_ring_header_t *header = pf_runq_header(vec, ring);
  return header->prod - header->cons;
}

always_inline void __pf_runq_ring_realloc(void **p, u32 new_size, u32 elt_bytes) {
  /*previous ring is too small*/
  void *old_ring = *p;
  void *old_elt, *new_elt;
  void *new_ring; 
  __pf_runq_ring_new_inline (&new_ring, elt_bytes, new_size, vec_get_align(old_ring));
  while ((old_elt = __vlib_pf_runq_ring_cons(old_ring)) != 0) {
    new_elt = __vlib_pf_runq_ring_prod(new_ring);
    ASSERT(new_elt != NULL && "failed to realloc pf runq");
    clib_memcpy_fast(new_elt, old_elt, elt_bytes);
  }
  vec_free(old_ring);
  p[0] = new_ring;
}

always_inline void* __pf_runq_ring_enqueue(void **ring_p)
{
    vlib_pf_runq_ring_header_t *header = pf_runq_header(*ring_p, ring);
    void *elt = __vlib_pf_runq_ring_prod(*ring_p);
    if (PREDICT_TRUE(elt != 0)) {
       return elt;
    }
    __pf_runq_ring_realloc(ring_p, header->ring_size * 2, header->elt_bytes);
    elt = __vlib_pf_runq_ring_prod(*ring_p);
    ASSERT(elt != 0 && "pf_runq realloc, but elt still is NULL");
    return elt;
}

always_inline void 
__pf_runq_ring_enq_bulk(void **ring_p, void *elts)
{
  void *ring_vec = *ring_p;
  vlib_pf_runq_ring_header_t *header = pf_runq_header(ring_vec, ring);
  u32 left = header->ring_size - __vlib_pf_runq_ring_len(ring_vec);
  u32 new_size = header->ring_size;
  while (left < vec_len(elts)) {
    left += new_size;
    new_size *= 2;
  }
  if (new_size > header->ring_size) {
    __pf_runq_ring_realloc(ring_p, new_size, header->elt_bytes);
  }
  ring_vec = *ring_p;
  header = pf_runq_header(ring_vec, ring);
  u32 i;
  void *new_elt;
  for (i = 0; i < vec_len(elts); i++) {
    new_elt = ____vlib_pf_runq_ring_prod(header, ring_vec);
    ASSERT(new_elt != NULL && "__pf_runq_ring_enq_bulk elt is NULL");
    clib_memcpy_fast(new_elt, elts + header->elt_bytes * i, header->elt_bytes);
  }
}

typedef struct
{
  u32 idx;
} vlib_pf_runq_stack_header_t;

always_inline void pf_runq_stack_reset(void *vec) {
  vlib_pf_runq_stack_header_t *header = pf_runq_header(vec, stack);
  header->idx = 0;
}

always_inline void
__pf_runq_stack_new_inline (u32 **p, u32 size, u32 align)
{
  void *stack;
  vec_attr_t va = {.elt_sz = sizeof(u32),
                   .hdr_sz = sizeof(vlib_pf_runq_stack_header_t),
                   .align = align};

  stack = _vec_alloc_internal (size, &va);
  pf_runq_stack_reset(stack);
  p[0] = stack;
}

always_inline u32*
__pf_runq_stack_enqueue(u32* vec)
{
  vlib_pf_runq_stack_header_t *header = pf_runq_header(vec, stack);
  vec_validate(vec, header->idx);
  return vec + (header->idx)++;
}

always_inline u32
__pf_runq_stack_len(u32* vec)
{
  vlib_pf_runq_stack_header_t *header = pf_runq_header(vec, stack);
  return header->idx; 
}

always_inline u32*
__pf_runq_stack_dequeue(u32* vec)
{
  if (PREDICT_FALSE(__pf_runq_stack_len(vec) == 0))
    return NULL;
  vlib_pf_runq_stack_header_t *header = pf_runq_header(vec, stack);
  return vec + --(header->idx);
}

always_inline void __pf_runq_stack_enq_bulk(u32 *vec, u32 *elts)
{
  vlib_pf_runq_stack_header_t *header = pf_runq_header(vec, stack);
  vec_validate(vec, vec_len(elts) + header->idx - 1);
  u32 i;
  for (i = 0; i < vec_len(elts); i++) {
    vec[(header->idx)++] = elts[i]; 
  }
} 
/* APIs */

#if PF_RUNQ_TYPE == 0

#define pf_runq_new_aligned(ring, size_shift, align) \
{ __pf_runq_ring_new_inline ((void **)&(ring), sizeof((ring)[0]), (1 << (size_shift)), align); }

#define pf_runq_new(ring, size_shift) \
{ __pf_runq_ring_new_inline ((void **)&(ring), sizeof((ring)[0]), (1 << (size_shift)), 0);}

#define pf_runq_free(f) vec_free ((f))

#define pf_runq_deq(ring) \
__vlib_pf_runq_ring_cons (ring)

#define pf_runq_try_enq(ring) \
__vlib_pf_runq_ring_prod (ring)

#define pf_runq_len(ring) \
__vlib_pf_runq_ring_len(ring)

#define pf_runq_enq(ring) \
__pf_runq_ring_enqueue ((void**)(&(ring)))

#define pf_runq_enq_bulk(vec, elts) \
__pf_runq_ring_enq_bulk((void**)(&(vec)), elts)

#elif PF_RUNQ_TYPE == 1

#define pf_runq_new_aligned(vec, size_shift, align) \
{ __pf_runq_stack_new_inline (&(vec), (1 << (size_shift)), align); }

#define pf_runq_new(vec, size_shift) \
{ __pf_runq_stack_new_inline (&(vec), (1 << (size_shift)), 0);}

#define pf_runq_free(f) vec_free ((f))

#define pf_runq_deq(vec) \
__pf_runq_stack_dequeue((vec))

#define pf_runq_len(vec) \
__pf_runq_stack_len((vec))

#define pf_runq_enq(vec) \
__pf_runq_stack_enqueue ((vec))

#define pf_runq_enq_bulk(vec, elts) \
__pf_runq_stack_enq_bulk(vec, elts)

#endif 