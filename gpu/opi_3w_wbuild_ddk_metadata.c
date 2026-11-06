// SPDX-License-Identifier: GPL-2.0-or-later
/* Expose the actual DDK header version for build and runtime validation. */
#include <linux/module.h>
#include <linux/moduleparam.h>
#include "pvrversion.h"
MODULE_INFO(opi_3w_wbuild_ddk, PVRVERSION_STRING_NUMERIC);
static char opi_3w_wbuild_ddk_string[] = PVRVERSION_STRING_NUMERIC;
module_param_string(opi_3w_wbuild_ddk, opi_3w_wbuild_ddk_string,
                    sizeof(opi_3w_wbuild_ddk_string), 0444);
MODULE_PARM_DESC(opi_3w_wbuild_ddk, "Compiled PowerVR DDK version");
