#ifndef included_vlib_pf_run_queue_h
#define included_vlib_pf_run_queue_h

#include "vppinfra/bitmap.h"
#include "vppinfra/clib.h"
#include "vppinfra/string.h"
#include "vppinfra/types.h"
#include "vppinfra/vec_bootstrap.h"
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

typedef struct
{
  u64 num_buckets;
  u32 bucket_budget;
  u64 *bucket_bitmap;
} vlib_pf_runq_cq_header_t;

typedef struct
{
  u32 budget;
  void *ring;
} vlib_pf_runq_cq_bucket_t;

#define pf_runq_cq_default_budget (bucket_size)

always_inline void
__pf_runq_cq_new_inline (void **p, u32 elt_bytes, u64 num_buckets,
			 u32 bucket_budget, u32 align)
{
  void *vec;
  vlib_pf_runq_cq_bucket_t *buckets, *bucket;
  u32 bucket_size;
  vec_attr_t va = {
    /* FIXME: Element size of the vector does not match the type of
       pointer to the vector; random access is prohibited */
    .elt_sz = sizeof (vlib_pf_runq_cq_bucket_t),
    .hdr_sz = sizeof (vlib_pf_runq_ring_header_t),
    .align = align,
  };
  vlib_pf_runq_cq_header_t *header;

  ASSERT ((num_buckets & (num_buckets - 1)) == 0 &&
	  "num_buckets should be power of 2");

  vec = _vec_alloc_internal (num_buckets, &va);
  header = pf_runq_header (vec, cq);
  bucket_size = bucket_budget; /* each element consumes 1 for now */

  clib_memset (header, 0, sizeof (*header));
  header->num_buckets = num_buckets;
  header->bucket_budget = bucket_budget;
  clib_bitmap_alloc (header->bucket_bitmap, num_buckets);

  buckets = vec;
  vec_foreach (bucket, buckets)
    {
      clib_memset (bucket, 0, sizeof (*bucket));
      __pf_runq_ring_new_inline (&bucket->ring, elt_bytes, bucket_size, align);
      bucket->budget = bucket_budget;
    }

  p[0] = vec;
}

always_inline void
pf_runq_cq_new_aligned (void **p, u32 elt_bytes, u64 num_buckets,
			u32 bucket_budget, u32 align)
{
  __pf_runq_cq_new_inline (p, elt_bytes, num_buckets, bucket_budget, align);
}

always_inline void
pf_runq_cq_new (void **p, u32 elt_bytes, u64 num_buckets, u32 bucket_budget)
{
  __pf_runq_cq_new_inline (p, elt_bytes, num_buckets, bucket_budget, 0);
}

always_inline void
pf_runq_cq_free (void *vec)
{
  vlib_pf_runq_cq_header_t *header = pf_runq_header (vec, cq);
  vlib_pf_runq_cq_bucket_t *buckets = vec, *bucket;

  vec_foreach (bucket, buckets)
    vec_free (bucket->ring);

  vec_free (header->bucket_bitmap);
  vec_free (vec);
}

always_inline void *
pf_runq_cq_cons (void *vec, u64 min_bucket_index)
{
  vlib_pf_runq_cq_header_t *header = pf_runq_header (vec, cq);
  vlib_pf_runq_cq_bucket_t *buckets = vec, *bucket, *min_bucket;
  u64 bucket_index;
  u32 expense;
  void *ring, *elt;

  /* Passing timestamp directly also works */
  min_bucket_index &= header->num_buckets - 1;

  bucket_index =
    clib_bitmap_next_set (header->bucket_bitmap, min_bucket_index);
  if (bucket_index == ~0)
    bucket_index = clib_bitmap_first_set (header->bucket_bitmap);

  if (PREDICT_FALSE (bucket_index == ~0))
    return NULL; /* calendar queue is empty */

  bucket = vec_elt_at_index (buckets, bucket_index);
  min_bucket = vec_elt_at_index (buckets, min_bucket_index);
  ring = bucket->ring;
  elt = __vlib_pf_runq_ring_cons (ring);

  ASSERT (elt != NULL && "ring is empty while bit in bitmap is set");

  if (min_bucket_index != bucket_index)
    {
      expense = 1; /* each element consumes 1 for now */
      bucket->budget += expense;
      if (min_bucket->budget >= expense)
	min_bucket->budget -= expense;
    }

  if (__vlib_pf_runq_ring_empty (pf_runq_header (ring, ring)))
    {
      clib_bitmap_set (header->bucket_bitmap, bucket_index, 0);
      /* FIXME: Is it the correct time to reset budget? */
      min_bucket->budget = header->bucket_budget;
    }

  return elt;
}

always_inline void *
__pf_runq_cq_prod (void *vec, u64 bucket_index, u32 expense)
{
  vlib_pf_runq_cq_header_t *header = pf_runq_header (vec, cq);
  vlib_pf_runq_cq_bucket_t *buckets = vec, *bucket;

  /* Passing timestamp directly also works */
  bucket_index &= header->num_buckets - 1;
  bucket = vec_elt_at_index (buckets, bucket_index);

  ASSERT (expense == 1 && "expense must be 1 for now");

  if (PREDICT_FALSE (bucket->budget < expense))
    return NULL; /* budget is not enough */
  else
    bucket->budget -= expense;

  if (PREDICT_FALSE (
	__vlib_pf_runq_ring_empty (pf_runq_header (bucket->ring, ring))))
    clib_bitmap_set (header->bucket_bitmap, bucket_index, 1);

  return __vlib_pf_runq_ring_prod (vec_elt (buckets, bucket_index).ring);
}

always_inline void *
pf_runq_cq_enq (void **p, u64 bucket_index, u32 expense)
{
  ASSERT (p != NULL && "vec is NULL");

  // TODO: Re-allocate if the queue is full
  return __pf_runq_cq_prod (*p, bucket_index, expense);
}

always_inline void
pf_runq_cq_enq_bulk (void **p, void *elts, u64 bucket_index, u32 total_expense)
{
  void *vec;
  vlib_pf_runq_cq_header_t *header;
  vlib_pf_runq_cq_bucket_t *buckets, *bucket;

  ASSERT (p != NULL && "vec is NULL");

  vec = *p;
  header = pf_runq_header (vec, cq);
  buckets = (vlib_pf_runq_cq_bucket_t *) vec;

  /* Passing timestamp directly also works */
  bucket_index &= header->num_buckets - 1;
  bucket = vec_elt_at_index (buckets, bucket_index);

  ASSERT (total_expense == vec_len (elts) &&
	  "total_expense must be equal to vec_len(elts) for now");

  if (PREDICT_FALSE (bucket->budget < total_expense))
    {
      if (CLIB_DEBUG > 0)
	clib_warning ("budget is not enough; skipping");
      return; /* budget is not enough */
    }
  else
    {
      bucket->budget -= total_expense;
    }

  if (PREDICT_FALSE (
	__vlib_pf_runq_ring_empty (pf_runq_header (bucket->ring, ring))))
    clib_bitmap_set (header->bucket_bitmap, bucket_index, 1);

  __pf_runq_ring_enq_bulk (&(bucket->ring), elts);
}

always_inline u32
pf_runq_cq_len (void *vec)
{
  vlib_pf_runq_cq_header_t *header = pf_runq_header (vec, cq);

  /* FIXME: This function returns 0/1 instead of the actual size */
  return clib_bitmap_first_set (header->bucket_bitmap) != ~0;
}

#define PF_PRIORITY_RUNQ_TYPE 0

#if PF_PRIORITY_RUNQ_TYPE == 0

#define pf_priority_runq_new_aligned(vec, size_shift, budget_shift, align)    \
  pf_runq_cq_new_aligned ((void **) &(vec), sizeof ((vec)[0]),                \
			  1 << (size_shift), 1 << (budget_shift), align)

#define pf_priority_runq_new(vec, size_shift, budget_shift)                   \
  pf_runq_cq_new ((void **) &(vec), sizeof ((vec)[0]), 1 << (size_shift),     \
		  1 << (budget_shift))

#define pf_priority_runq_free(vec) pf_runq_cq_free ((vec))

#define pf_priority_runq_deq(vec, min_priority)                               \
  ((typeof ((vec)[0]) *) pf_runq_cq_cons ((vec), (min_priority)))

#define pf_priority_runq_len(vec) pf_runq_cq_len ((vec))

#define pf_priority_runq_enq(vec, priority, expense)                          \
  ((typeof ((vec)[0]) *) pf_runq_cq_enq ((void **) &(vec), (priority),        \
					 (expense)))

#define pf_priority_runq_enq_bulk(vec, elts, priority, total_expense)         \
  pf_runq_cq_enq_bulk ((void **) &(vec), (elts), (priority), (total_expense))

#endif /* PF_PRIORITY_RUNQ_TYPE */

#endif /* included_vlib_pf_run_queue_h */
