/* SPDX-License-Identifier: GPL-2.0-or-later
 * Direct VIPLite inference probe. There is no CPU model execution path.
 */
#include <vip_lite.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <math.h>
#include <time.h>
#define CHECK(call) do {vip_status_e e=(call);if(e!=VIP_SUCCESS){fprintf(stderr,"NPU_API_ERROR %s status=%d\n",#call,(int)e);goto cleanup;}}while(0)
#define REQUIRE(test,message) do {if(!(test)){fprintf(stderr,"NPU_PROBE_ERROR %s\n",message);goto cleanup;}}while(0)
static int parameters(vip_network n,int output,vip_buffer_create_params_t *p){
 memset(p,0,sizeof(*p));p->memory_type=VIP_BUFFER_MEMORY_TYPE_DEFAULT;
 #define Q(prop,ptr) do {vip_status_e s=output?vip_query_output(n,0,prop,ptr):vip_query_input(n,0,prop,ptr);if(s!=VIP_SUCCESS){fprintf(stderr,"NPU_API_ERROR query_%s %s status=%d\n",output?"output":"input",#prop,(int)s);return -1;}}while(0)
 Q(VIP_BUFFER_PROP_NUM_OF_DIMENSION,&p->num_of_dims);Q(VIP_BUFFER_PROP_SIZES_OF_DIMENSION,p->sizes);
 Q(VIP_BUFFER_PROP_DATA_FORMAT,&p->data_format);Q(VIP_BUFFER_PROP_QUANT_FORMAT,&p->quant_format);
 if(p->quant_format==VIP_BUFFER_QUANTIZE_TF_ASYMM){Q(VIP_BUFFER_PROP_TF_SCALE,&p->quant_data.affine.scale);Q(VIP_BUFFER_PROP_TF_ZERO_POINT,&p->quant_data.affine.zeroPoint);}
 else if(p->quant_format==VIP_BUFFER_QUANTIZE_DYNAMIC_FIXED_POINT){Q(VIP_BUFFER_PROP_FIXED_POINT_POS,&p->quant_data.dfp.fixed_point_pos);}
 #undef Q
 return 0;
}
static size_t elements(const vip_buffer_create_params_t *p){
 if(p->num_of_dims==0||p->num_of_dims>6)return 0;
 size_t n=1;for(unsigned i=0;i<p->num_of_dims;i++){if(!p->sizes[i]||p->sizes[i]>100000||n>100000/p->sizes[i])return 0;n*=p->sizes[i];}return n;
}
/* IEEE 754 binary16, including subnormals, signed zero and nonfinite values.
 * No compiler half-float extension or ARM FP16 instruction is required. */
static double binary16(uint16_t bits){
 unsigned exponent=(bits>>10)&31, fraction=bits&1023;
 double value=exponent==31?(fraction?NAN:INFINITY):
              exponent?ldexp(1024.0+fraction,(int)exponent-25):ldexp((double)fraction,-24);
 return bits&0x8000?-value:value;
}
static size_t element_bytes(vip_enum format){
 switch(format){
 case VIP_BUFFER_FORMAT_FP32:return 4;
 case VIP_BUFFER_FORMAT_FP16:case VIP_BUFFER_FORMAT_INT16:return 2;
 case VIP_BUFFER_FORMAT_UINT8:case VIP_BUFFER_FORMAT_INT8:return 1;
 default:return 0;
 }
}
static double decode(const void *data,size_t i,const vip_buffer_create_params_t *p){
 double v;
 switch(p->data_format){
 case VIP_BUFFER_FORMAT_FP32:v=((const float*)data)[i];break;
 case VIP_BUFFER_FORMAT_FP16:v=binary16(((const uint16_t*)data)[i]);break;
 case VIP_BUFFER_FORMAT_UINT8:v=((const uint8_t*)data)[i];break;
 case VIP_BUFFER_FORMAT_INT8:v=((const int8_t*)data)[i];break;
 case VIP_BUFFER_FORMAT_INT16:v=((const int16_t*)data)[i];break;
 default:return NAN;
 }
 if(p->data_format!=VIP_BUFFER_FORMAT_FP32&&p->data_format!=VIP_BUFFER_FORMAT_FP16){
  if(p->quant_format==VIP_BUFFER_QUANTIZE_TF_ASYMM)v=(v-p->quant_data.affine.zeroPoint)*p->quant_data.affine.scale;
  else if(p->quant_format==VIP_BUFFER_QUANTIZE_DYNAMIC_FIXED_POINT)v=ldexp(v,-p->quant_data.dfp.fixed_point_pos);
  else if(p->quant_format!=VIP_BUFFER_QUANTIZE_NONE)return NAN;
 }
 return v;
}
int main(int argc,char **argv){
 if(argc!=4){fprintf(stderr,"Usage: npu-probe model.nb input0.u8 input1.u8\n");return 2;}
 setbuf(stdout,NULL);setbuf(stderr,NULL);
 vip_network network=NULL;vip_buffer input=NULL,output=NULL;int initialized=0,prepared=0,rc=1,mapped_output=0;void *mapped=NULL;
 vip_buffer_create_params_t ip,op;vip_uint32_t cid=0,devices=0,count=0,version=vip_get_version();
 double scores[6][10],times[6];vip_inference_profile_t profiles[6]={{0}};
 CHECK(vip_init());initialized=1;
 CHECK(vip_query_hardware(VIP_QUERY_HW_PROP_CID,sizeof(cid),&cid));CHECK(vip_query_hardware(VIP_QUERY_HW_PROP_DEVICE_COUNT,sizeof(devices),&devices));
 fprintf(stderr,"NPU_HARDWARE cid=0x%08x devices=%u api=0x%08x\n",cid,devices,version);
 if(cid!=0x1000003b||devices!=1){fprintf(stderr,"Unexpected hardware identity\n");goto cleanup;}
 CHECK(vip_create_network(argv[1],0,VIP_CREATE_NETWORK_FROM_FILE,&network));
 CHECK(vip_query_network(network,VIP_NETWORK_PROP_INPUT_COUNT,&count));REQUIRE(count==1,"Expected one network input");
 CHECK(vip_query_network(network,VIP_NETWORK_PROP_OUTPUT_COUNT,&count));REQUIRE(count==1,"Expected one network output");
 if(parameters(network,0,&ip)||parameters(network,1,&op))goto cleanup;
 fprintf(stderr,"NPU_TENSORS input_format=%d input_quantization=%d input_elements=%zu output_format=%d output_quantization=%d output_elements=%zu\n",ip.data_format,ip.quant_format,elements(&ip),op.data_format,op.quant_format,elements(&op));
 if(elements(&ip)!=784||elements(&op)!=10||ip.data_format!=VIP_BUFFER_FORMAT_UINT8){fprintf(stderr,"Unsupported LeNet tensor layout/type\n");goto cleanup;}
 /* lenet.dat contains the SDK's raw uint8 tensor, not floating point pixels. */
 CHECK(vip_create_buffer(&ip,0,&input));CHECK(vip_create_buffer(&op,0,&output));
 size_t output_element_bytes=element_bytes(op.data_format);
 REQUIRE(output_element_bytes,"Unsupported output tensor format");
 if(op.data_format==VIP_BUFFER_FORMAT_FP16||op.data_format==VIP_BUFFER_FORMAT_FP32)REQUIRE(op.quant_format==VIP_BUFFER_QUANTIZE_NONE,"Unexpected quantization on floating point output");
 if(vip_get_buffer_size(input)!=784||vip_get_buffer_size(output)<10*output_element_bytes||vip_get_buffer_size(output)>4096){fprintf(stderr,"Unexpected buffer bytes\n");goto cleanup;}
 vip_uint32_t timeout=10000;CHECK(vip_set_network(network,VIP_NETWORK_PROP_SET_TIME_OUT,&timeout));
 CHECK(vip_prepare_network(network));prepared=1;
 /* VIPLite patches prepared command buffers when attaching network I/O. */
 CHECK(vip_set_input(network,0,input));CHECK(vip_set_output(network,0,output));
 for(int run=0;run<6;run++){
  FILE *f=fopen(argv[2+(run%2)],"rb");uint8_t data[784];
  if(!f){perror("input");goto cleanup;}size_t bytes=fread(data,1,sizeof(data),f);int tail=fgetc(f);fclose(f);
  REQUIRE(bytes==sizeof(data)&&tail==EOF,"Input file must contain exactly 784 bytes");
  mapped_output=0;mapped=vip_map_buffer(input);REQUIRE(mapped,"vip_map_buffer(input) returned NULL");memcpy(mapped,data,sizeof(data));CHECK(vip_unmap_buffer(input));mapped=NULL;
  CHECK(vip_flush_buffer(input,VIP_BUFFER_OPER_TYPE_FLUSH));
  struct timespec a,b;REQUIRE(clock_gettime(CLOCK_MONOTONIC,&a)==0,"clock_gettime before inference failed");CHECK(vip_run_network(network));REQUIRE(clock_gettime(CLOCK_MONOTONIC,&b)==0,"clock_gettime after inference failed");
  times[run]=(b.tv_sec-a.tv_sec)*1000.0+(b.tv_nsec-a.tv_nsec)/1e6;
  CHECK(vip_query_network(network,VIP_NETWORK_PROP_PROFILING,&profiles[run]));
  if(!profiles[run].total_cycle){fprintf(stderr,"No hardware inference cycles reported\n");goto cleanup;}
  CHECK(vip_flush_buffer(output,VIP_BUFFER_OPER_TYPE_INVALIDATE));mapped_output=1;mapped=vip_map_buffer(output);REQUIRE(mapped,"vip_map_buffer(output) returned NULL");
  for(int j=0;j<10;j++){scores[run][j]=decode(mapped,j,&op);if(!isfinite(scores[run][j])){fprintf(stderr,"NPU_PROBE_ERROR Nonfinite output run=%d index=%d format=%d quantization=%d\n",run,j,op.data_format,op.quant_format);goto cleanup;}}
  CHECK(vip_unmap_buffer(output));mapped=NULL;
 }
 printf("NPU_RESULT={\"schema\":1,\"cid\":%u,\"devices\":%u,\"api_version\":%u,\"input_format\":%d,\"input_quantization\":%d,\"output_format\":%d,\"runs\":[",cid,devices,version,ip.data_format,ip.quant_format,op.data_format);
 for(int run=0;run<6;run++){
  printf("%s{\"case_index\":%d,\"milliseconds\":%.6f,\"hardware_cycles\":%u,\"hardware_microseconds\":%u,\"scores\":[",run?",":"",run%2,times[run],profiles[run].total_cycle,profiles[run].inference_time);
  for(int j=0;j<10;j++)printf("%s%.9g",j?",":"",scores[run][j]);printf("]}");
 }
 printf("]}\n");rc=0;
cleanup:
 #define CLEAN(call) do {if((call)!=VIP_SUCCESS){fprintf(stderr,"NPU cleanup failed: %s\n",#call);rc=1;}}while(0)
 if(mapped)CLEAN(vip_unmap_buffer(mapped_output?output:input));
 if(prepared)CLEAN(vip_finish_network(network));
 if(output)CLEAN(vip_destroy_buffer(output));if(input)CLEAN(vip_destroy_buffer(input));
 if(network)CLEAN(vip_destroy_network(network));if(initialized)CLEAN(vip_destroy());
 return rc;
}
