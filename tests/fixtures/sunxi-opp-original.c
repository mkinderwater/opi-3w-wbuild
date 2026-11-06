/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Copyright(c) 2023 - 2030 Allwinner Technology Co.,Ltd. All rights reserved. */
/*
 * Copyright (c) 2023-2030 Allwinnertech Co., Ltd.
 *
 * This software is licensed under the terms of the GNU General Public
 * License version 2, as published by the Free Software opi-3w-wbuild, and
 * may be copied, distributed, and modified under those terms.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
 * GNU General Public License for more details.
 *
 * Author: zhengwanyu<zhengwanyu@allwinnertech.com>
 */

extern void DIPrintf(const OSDI_IMPL_ENTRY *psEntry, const IMG_CHAR *pszFmt, ...);
static int _DebugDumpOppInfoDIShow(OSDI_IMPL_ENTRY *psEntry, void *pvData)
{
	int i = 0;
	struct sunxi_platform *sunxi_data;

	sunxi_data = (struct sunxi_platform *)psEntry->pvPrivData;
	if (!sunxi_data) {
		DIPrintf(psEntry, "Null sunxi_data\n");
		return -1;
	}

	if (!psEntry) {
		DIPrintf(psEntry, "Null psEntry\n");
		return -1;
	}

	for (i = 0; i < sunxi_data->ui32OPPTableSize; i++) {
		DIPrintf(psEntry, "opp%d is %luHz---%lumV\n",
				  i, sunxi_data->asOPPTable[i].ui32Freq,
				  sunxi_data->asOPPTable[i].ui32Volt / 1000);
	}

	return 0;
}

