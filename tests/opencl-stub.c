#define CL_TARGET_OPENCL_VERSION 120
#include <CL/cl.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <math.h>
static cl_mem active;
static int mode(const char *s){const char *m=getenv("CL_TEST_MODE");return m && strcmp(m,s)==0;}
cl_int clGetPlatformIDs(cl_uint n,cl_platform_id *p,cl_uint *count){if(mode("no-platform"))return -1001;if(count)*count=1;if(p&&n)p[0]=(cl_platform_id)(uintptr_t)1;return CL_SUCCESS;}
cl_int clGetDeviceIDs(cl_platform_id p,cl_device_type type,cl_uint n,cl_device_id *d,cl_uint *count){if(type!=CL_DEVICE_TYPE_GPU||mode("cpu-only"))return CL_DEVICE_NOT_FOUND;if(count)*count=1;if(n&&d)d[0]=(cl_device_id)(uintptr_t)1;return CL_SUCCESS;}
cl_int clGetDeviceInfo(cl_device_id d,cl_device_info key,size_t size,void *out,size_t *ret){const char *s=key==CL_DEVICE_NAME?(mode("wrong-gpu")?"Other GPU":"PowerVR BXM-4-64"):"test-driver";if(out&&size)strncpy(out,s,size);return CL_SUCCESS;}
cl_context clCreateContext(const cl_context_properties *p,cl_uint n,const cl_device_id *d,void (CL_CALLBACK *notify)(const char*,const void*,size_t,void*),void *u,cl_int *err){*err=0;return (cl_context)(uintptr_t)1;}
cl_command_queue clCreateCommandQueue(cl_context c,cl_device_id d,cl_command_queue_properties p,cl_int *err){*err=0;return (cl_command_queue)(uintptr_t)1;}
cl_program clCreateProgramWithSource(cl_context c,cl_uint n,const char **s,const size_t *l,cl_int *err){*err=0;return (cl_program)(uintptr_t)1;}
cl_int clBuildProgram(cl_program p,cl_uint n,const cl_device_id *d,const char *opts,void (CL_CALLBACK *notify)(cl_program,void*),void *u){return mode("compile-failure")?CL_BUILD_PROGRAM_FAILURE:0;}
cl_int clGetProgramBuildInfo(cl_program p,cl_device_id d,cl_program_build_info k,size_t size,void *v,size_t *r){if(v&&size)((char*)v)[0]=0;return 0;}
cl_kernel clCreateKernel(cl_program p,const char *name,cl_int *err){*err=0;return (cl_kernel)(uintptr_t)1;}
cl_mem clCreateBuffer(cl_context c,cl_mem_flags f,size_t size,void *data,cl_int *err){void *p=malloc(size);if(!p){*err=CL_OUT_OF_HOST_MEMORY;return NULL;}memcpy(p,data,size);*err=0;return (cl_mem)p;}
cl_int clSetKernelArg(cl_kernel k,cl_uint i,size_t size,const void *arg){active=*(const cl_mem*)arg;return 0;}
cl_int clEnqueueNDRangeKernel(cl_command_queue q,cl_kernel k,cl_uint dims,const size_t *offset,const size_t *global,const size_t *local,cl_uint n,const cl_event *events,cl_event *result){float *v=(float*)active;for(size_t i=0;i<global[0];i++)v[i]+=1.0f;if(mode("wrong-result"))v[0]=8.0f;if(mode("nan"))v[0]=NAN;return 0;}
cl_int clEnqueueReadBuffer(cl_command_queue q,cl_mem b,cl_bool blocking,size_t offset,size_t size,void *out,cl_uint n,const cl_event *events,cl_event *result){memcpy(out,(char*)b+offset,size);return 0;}
cl_int clReleaseMemObject(cl_mem p){free(p);return 0;}
cl_int clReleaseKernel(cl_kernel p){return 0;}
cl_int clReleaseProgram(cl_program p){return 0;}
cl_int clReleaseCommandQueue(cl_command_queue p){return 0;}
cl_int clReleaseContext(cl_context p){return 0;}
