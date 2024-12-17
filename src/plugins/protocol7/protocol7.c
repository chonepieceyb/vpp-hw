/*
 * protocol7.c - skeleton vpp engine plug-in
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

#include <vnet/vnet.h>
#include <vnet/plugin/plugin.h>
#include <protocol7/protocol7.h>

#include <vlibapi/api.h>
#include <vlibmemory/api.h>
#include <vpp/app/version.h>
#include <stdbool.h>

#include <protocol7/protocol7.api_enum.h>
#include <protocol7/protocol7.api_types.h>

#define REPLY_MSG_ID_BASE pmp->msg_id_base
#include <vlibapi/api_helper_macros.h>

protocol7_main_t protocol7_main;

/* Action function shared between message handler and debug CLI */

int protocol7_enable_disable (protocol7_main_t * pmp, u32 sw_if_index,
                                   int enable_disable)
{
  vnet_sw_interface_t * sw;
  int rv = 0;

  /* Utterly wrong? */
  if (pool_is_free_index (pmp->vnet_main->interface_main.sw_interfaces,
                          sw_if_index))
    return VNET_API_ERROR_INVALID_SW_IF_INDEX;

  /* Not a physical port? */
  sw = vnet_get_sw_interface (pmp->vnet_main, sw_if_index);
  if (sw->type != VNET_SW_INTERFACE_TYPE_HARDWARE)
    return VNET_API_ERROR_INVALID_SW_IF_INDEX;

  protocol7_create_periodic_process (pmp);

  vnet_feature_enable_disable ("device-input", "protocol7",
                               sw_if_index, enable_disable, 0, 0);

  /* Send an event to enable/disable the periodic scanner process */
  vlib_process_signal_event (pmp->vlib_main,
                             pmp->periodic_node_index,
                             PROTOCOL7_EVENT_PERIODIC_ENABLE_DISABLE,
                            (uword)enable_disable);
  return rv;
}

static clib_error_t *
protocol7_enable_disable_command_fn (vlib_main_t * vm,
                                   unformat_input_t * input,
                                   vlib_cli_command_t * cmd)
{
  protocol7_main_t * pmp = &protocol7_main;
  u32 sw_if_index = ~0;
  int enable_disable = 1;

  int rv;

  while (unformat_check_input (input) != UNFORMAT_END_OF_INPUT)
    {
      if (unformat (input, "disable"))
        enable_disable = 0;
      else if (unformat (input, "%U", unformat_vnet_sw_interface,
                         pmp->vnet_main, &sw_if_index))
        ;
      else
        break;
  }

  if (sw_if_index == ~0)
    return clib_error_return (0, "Please specify an interface...");

  rv = protocol7_enable_disable (pmp, sw_if_index, enable_disable);

  switch(rv)
    {
  case 0:
    break;

  case VNET_API_ERROR_INVALID_SW_IF_INDEX:
    return clib_error_return
      (0, "Invalid interface, only works on physical ports");
    break;

  case VNET_API_ERROR_UNIMPLEMENTED:
    return clib_error_return (0, "Device driver doesn't support redirection");
    break;

  default:
    return clib_error_return (0, "protocol7_enable_disable returned %d",
                              rv);
    }
  return 0;
}

/* *INDENT-OFF* */
VLIB_CLI_COMMAND (protocol7_enable_disable_command, static) =
{
  .path = "protocol7 enable-disable",
  .short_help =
  "protocol7 enable-disable <interface-name> [disable]",
  .function = protocol7_enable_disable_command_fn,
};
/* *INDENT-ON* */

/* API message handler */
static void vl_api_protocol7_enable_disable_t_handler
(vl_api_protocol7_enable_disable_t * mp)
{
  vl_api_protocol7_enable_disable_reply_t * rmp;
  protocol7_main_t * pmp = &protocol7_main;
  int rv;

  rv = protocol7_enable_disable (pmp, ntohl(mp->sw_if_index),
                                      (int) (mp->enable_disable));

  REPLY_MACRO(VL_API_PROTOCOL7_ENABLE_DISABLE_REPLY);
}

/* API definitions */
#include <protocol7/protocol7.api.c>

static clib_error_t * protocol7_init (vlib_main_t * vm)
{
  protocol7_main_t * pmp = &protocol7_main;
  clib_error_t * error = 0;

  pmp->vlib_main = vm;
  pmp->vnet_main = vnet_get_main();

  /* Add our API messages to the global name_crc hash table */
  pmp->msg_id_base = setup_message_id_table ();

  return error;
}

VLIB_INIT_FUNCTION (protocol7_init);

/* *INDENT-OFF* */
VNET_FEATURE_INIT (protocol7, static) =
{
  .arc_name = "device-input",
  .node_name = "protocol7",
  .runs_before = VNET_FEATURES ("ethernet-input"),
};
/* *INDENT-ON */

/* *INDENT-OFF* */
VLIB_PLUGIN_REGISTER () =
{
  .version = VPP_BUILD_VER,
  .description = "protocol7 plugin description goes here",
};
/* *INDENT-ON* */

/*
 * fd.io coding-style-patch-verification: ON
 *
 * Local Variables:
 * eval: (c-set-style "gnu")
 * End:
 */
