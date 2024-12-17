/*
 * node.c - skeleton vpp engine plug-in dual-loop node skeleton
 *
 * Copyright (c) <current-year> <your-organization>
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

#include <protocol11/protocol11.h>


#include <vlib/vlib.h>
#include <vnet/pg/pg.h>
#include <vnet/vnet.h>
#include <vppinfra/error.h>
#include <vppinfra/xxhash.h>
#include "../protocol_node_fn.h"

DECLARE_PROTOCOL_NODE(protocol11, protocol11_1)
DECLARE_PROTOCOL_NODE(protocol11_1, protocol11_2)
DECLARE_PROTOCOL_NODE(protocol11_2, ip6-lookup)