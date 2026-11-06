/* Host test double only; never installed in an image or runtime archive. */
#include <vip_lite.h>
#include <stdlib.h>
#include <string.h>
#include "fake_golden.h"
struct _vip_buffer {unsigned char data[784];int output;vip_enum format;};
struct _vip_network {vip_buffer input,output;int prepared;};
static int fail(const char *name){const char *s=getenv("NPU_FAKE_MODE");return s&&strcmp(s,name)==0;}
vip_uint32_t vip_get_version(void){return 0x20003;}
vip_status_e vip_init(void){return fail("init")?VIP_ERROR_FAILURE:VIP_SUCCESS;}
vip_status_e vip_destroy(void){return fail("cleanup")?VIP_ERROR_FAILURE:VIP_SUCCESS;}
vip_status_e vip_query_hardware(vip_query_hardware_property_e p,vip_uint32_t n,void *v){(void)n;*(vip_uint32_t*)v=p==VIP_QUERY_HW_PROP_CID?(fail("cid")?0:0x1000003b):1;return VIP_SUCCESS;}
vip_status_e vip_create_network(const void *d,vip_uint32_t n,vip_create_network_type_e t,vip_network *out){(void)d;(void)n;(void)t;*out=calloc(1,sizeof(**out));return *out?VIP_SUCCESS:VIP_ERROR_FAILURE;}
vip_status_e vip_destroy_network(vip_network n){free(n);return VIP_SUCCESS;}
vip_status_e vip_query_network(vip_network n,vip_enum p,void *v){(void)n;if(p==VIP_NETWORK_PROP_PROFILING){vip_inference_profile_t *r=v;r->total_cycle=fail("profile")?0:65000;r->inference_time=80;}else *(vip_uint32_t*)v=1;return VIP_SUCCESS;}
vip_status_e vip_set_network(vip_network n,vip_enum p,void *v){(void)n;(void)p;(void)v;return VIP_SUCCESS;}
static vip_status_e query(int output,vip_enum p,void *v){
 switch(p){case VIP_BUFFER_PROP_NUM_OF_DIMENSION:*(vip_uint32_t*)v=4;break;
 case VIP_BUFFER_PROP_SIZES_OF_DIMENSION:{vip_uint32_t *s=v;s[0]=output?10:28;s[1]=output?1:28;s[2]=s[3]=1;break;}
 case VIP_BUFFER_PROP_DATA_FORMAT:*(vip_enum*)v=output?(fail("fp32")?VIP_BUFFER_FORMAT_FP32:fail("unsupported")?VIP_BUFFER_FORMAT_BFP16:VIP_BUFFER_FORMAT_FP16):VIP_BUFFER_FORMAT_UINT8;break;
 case VIP_BUFFER_PROP_QUANT_FORMAT:*(vip_enum*)v=VIP_BUFFER_QUANTIZE_NONE;break;default:break;}return VIP_SUCCESS;
}
vip_status_e vip_query_input(vip_network n,vip_uint32_t i,vip_enum p,void *v){(void)n;(void)i;return query(0,p,v);}
vip_status_e vip_query_output(vip_network n,vip_uint32_t i,vip_enum p,void *v){(void)n;(void)i;return query(1,p,v);}
vip_status_e vip_create_buffer(vip_buffer_create_params_t *p,vip_uint32_t z,vip_buffer *out){(void)z;*out=calloc(1,sizeof(**out));if(!*out)return VIP_ERROR_FAILURE;(*out)->output=p->sizes[0]==10;(*out)->format=p->data_format;return VIP_SUCCESS;}
vip_status_e vip_destroy_buffer(vip_buffer b){free(b);return VIP_SUCCESS;}
void *vip_map_buffer(vip_buffer b){if(fail(b->output?"map_output":"map_input"))return NULL;return b->data;}
vip_status_e vip_unmap_buffer(vip_buffer b){(void)b;return VIP_SUCCESS;}
vip_uint32_t vip_get_buffer_size(vip_buffer b){return b->output?(fail("short_buffer")?10:b->format==VIP_BUFFER_FORMAT_FP32?40:20):784;}
vip_status_e vip_flush_buffer(vip_buffer b,vip_buffer_operation_type_e p){(void)b;(void)p;return VIP_SUCCESS;}
vip_status_e vip_set_input(vip_network n,vip_uint32_t i,vip_buffer b){(void)i;if(!n->prepared)return VIP_ERROR_FAILURE;n->input=b;return VIP_SUCCESS;}
vip_status_e vip_set_output(vip_network n,vip_uint32_t i,vip_buffer b){(void)i;if(!n->prepared)return VIP_ERROR_FAILURE;n->output=b;return VIP_SUCCESS;}
vip_status_e vip_prepare_network(vip_network n){if(fail("prepare"))return VIP_ERROR_FAILURE;n->prepared=1;return VIP_SUCCESS;}
vip_status_e vip_finish_network(vip_network n){if(!n->prepared)return VIP_ERROR_FAILURE;n->prepared=0;return VIP_SUCCESS;}
vip_status_e vip_run_network(vip_network n){
 if(fail("run")||!n->prepared||!n->input||!n->output)return VIP_ERROR_FAILURE;
 int which=n->input->data[0];if(which>1)return VIP_ERROR_INVALID_ARGUMENTS;
 for(int i=0;i<784;i++)if(n->input->data[i]!=which)return VIP_ERROR_INVALID_ARGUMENTS;
 if(fail("stale"))which=0;
 if(n->output->format==VIP_BUFFER_FORMAT_FP32){float scores[10];for(int j=0;j<10;j++)scores[j]=fake_scores[which][j];memcpy(n->output->data,scores,sizeof(scores));}
 else {memcpy(n->output->data,fake_half_scores[which],20);if(fail("nonfinite")){unsigned short nan=0x7e00;memcpy(n->output->data,&nan,2);}}
 return VIP_SUCCESS;
}
