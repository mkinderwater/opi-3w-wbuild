#define _POSIX_C_SOURCE 200809L
#define CL_TARGET_OPENCL_VERSION 120
#include <stdlib.h>
#include <CL/cl.h>
#include <stdio.h>
#include <string.h>

/* A real GPU kernel test, not just a shared-library or platform-presence test. */
int main(void)
{
    cl_platform_id platforms[16];
    cl_uint count=0;
    cl_int err=clGetPlatformIDs(16,platforms,&count);
    if (err!=CL_SUCCESS || count==0) {
        fprintf(stderr,"FAIL: no OpenCL platform (%d)\n",err);return 1;
    }
    cl_device_id device=NULL;
    for (cl_uint i=0;i<count && i<16 && !device;i++) {
        cl_device_id devices[16];cl_uint n=0;
        if (clGetDeviceIDs(platforms[i],CL_DEVICE_TYPE_GPU,16,devices,&n)!=CL_SUCCESS) continue;
        for (cl_uint j=0;j<n && j<16;j++) {
            char name[256]={0};
            if (clGetDeviceInfo(devices[j],CL_DEVICE_NAME,sizeof(name)-1,name,NULL)==CL_SUCCESS && strstr(name,"BXM-4-64")) {
                device=devices[j];printf("GPU: %s\n",name);break;
            }
        }
    }
    if (!device) {fprintf(stderr,"FAIL: no PowerVR BXM-4-64 OpenCL GPU\n");return 1;}
    char api[256]={0}, extensions[16384]={0};
    clGetDeviceInfo(device,CL_DEVICE_VERSION,sizeof(api)-1,api,NULL);
    clGetDeviceInfo(device,CL_DEVICE_EXTENSIONS,sizeof(extensions)-1,extensions,NULL);
    printf("OpenCL: %s\nFP16 extension: %s\n",api,strstr(extensions,"cl_khr_fp16")?"present":"not advertised");
    char version[256]={0};
    clGetDeviceInfo(device,CL_DRIVER_VERSION,sizeof(version)-1,version,NULL);
    printf("Driver: %s\n",version);
    cl_context context=NULL;cl_command_queue queue=NULL;cl_program program=NULL;
    cl_kernel kernel=NULL;cl_mem buffer=NULL;int result=1;
    float data[16];for (int i=0;i<16;i++) data[i]=(float)i;
    const char *code="__kernel void add(__global float *v){size_t i=get_global_id(0);v[i]=v[i]+1.0f;}";
#define REQUIRE_OK() do {if (err!=CL_SUCCESS) {fprintf(stderr,"FAIL: %s:%d OpenCL error %d\n",__FILE__,__LINE__,err);goto cleanup;}} while(0)
    context=clCreateContext(NULL,1,&device,NULL,NULL,&err);REQUIRE_OK();
    queue=clCreateCommandQueue(context,device,0,&err);REQUIRE_OK();
    program=clCreateProgramWithSource(context,1,&code,NULL,&err);REQUIRE_OK();
    err=clBuildProgram(program,1,&device,"",NULL,NULL);
    if (err!=CL_SUCCESS) {
        char log[4096]={0};clGetProgramBuildInfo(program,device,CL_PROGRAM_BUILD_LOG,sizeof(log)-1,log,NULL);
        fprintf(stderr,"Build log: %s\n",log);goto cleanup;
    }
    kernel=clCreateKernel(program,"add",&err);REQUIRE_OK();
    buffer=clCreateBuffer(context,CL_MEM_READ_WRITE|CL_MEM_COPY_HOST_PTR,sizeof(data),data,&err);REQUIRE_OK();
    err=clSetKernelArg(kernel,0,sizeof(buffer),&buffer);REQUIRE_OK();
    size_t global=16;
    err=clEnqueueNDRangeKernel(queue,kernel,1,NULL,&global,NULL,0,NULL,NULL);REQUIRE_OK();
    err=clEnqueueReadBuffer(queue,buffer,CL_TRUE,0,sizeof(data),data,0,NULL,NULL);REQUIRE_OK();
    for (int i=0;i<16;i++) {
        float expected=(float)(i+1);
        /* Both comparisons reject NaN, which must never count as success. */
        if (!(data[i]>=expected-0.0001f && data[i]<=expected+0.0001f)) {
            fprintf(stderr,"FAIL: output[%d]=%g, expected %g\n",i,(double)data[i],(double)expected);goto cleanup;
        }
    }
    puts("PASS: PowerVR BXM-4-64 compiled and executed an OpenCL kernel; results verified");result=0;
cleanup:
    if (buffer) clReleaseMemObject(buffer);
    if (kernel) clReleaseKernel(kernel);
    if (program) clReleaseProgram(program);
    if (queue) clReleaseCommandQueue(queue);
    if (context) clReleaseContext(context);
    return result;
}
