#define _POSIX_C_SOURCE 200809L
#include <vulkan/vulkan.h>
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "gpu-shader.h"

#define VK_OK(expr) do { VkResult e=(expr); if(e!=VK_SUCCESS){fprintf(stderr,"FAIL: %s returned %d\n",#expr,(int)e);goto cleanup;} } while(0)
int main(void) {
    int result=1; void *mapped=NULL;
    VkInstance instance=VK_NULL_HANDLE; VkDevice device=VK_NULL_HANDLE;
    VkBuffer buffer=VK_NULL_HANDLE; VkDeviceMemory memory=VK_NULL_HANDLE;
    VkDescriptorSetLayout setlayout=VK_NULL_HANDLE; VkPipelineLayout layout=VK_NULL_HANDLE;
    VkShaderModule shader=VK_NULL_HANDLE; VkPipeline pipeline=VK_NULL_HANDLE;
    VkDescriptorPool pool=VK_NULL_HANDLE; VkCommandPool commandpool=VK_NULL_HANDLE;
    VkPhysicalDevice physical=VK_NULL_HANDLE;
    /* Select only the intended ICD; never accept a software Vulkan fallback. */
    if(!getenv("VK_DRIVER_FILES")) setenv("VK_DRIVER_FILES","/opt/opi-3w-wbuild-powervr/img_icd.json",1);
    VkApplicationInfo app={.sType=VK_STRUCTURE_TYPE_APPLICATION_INFO,.pApplicationName="opi-3w-wbuild-numeric",.apiVersion=VK_API_VERSION_1_0};
    VkInstanceCreateInfo ci={.sType=VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO,.pApplicationInfo=&app};
    VK_OK(vkCreateInstance(&ci,NULL,&instance));
    uint32_t count=16; VkPhysicalDevice devices[16];
    VK_OK(vkEnumeratePhysicalDevices(instance,&count,devices));
    for(uint32_t i=0;i<count && i<16;i++) {
        VkPhysicalDeviceProperties properties; vkGetPhysicalDeviceProperties(devices[i],&properties);
        if(strstr(properties.deviceName,"BXM-4-64") && properties.deviceType==VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU) {
            physical=devices[i];printf("GPU: %s\nVulkan device API: %u.%u.%u\n",properties.deviceName,VK_API_VERSION_MAJOR(properties.apiVersion),VK_API_VERSION_MINOR(properties.apiVersion),VK_API_VERSION_PATCH(properties.apiVersion));break;
        }
    }
    if(!physical){fputs("FAIL: no hardware PowerVR BXM-4-64 Vulkan GPU\n",stderr);goto cleanup;}
    uint32_t families=32, family=UINT32_MAX; VkQueueFamilyProperties queues[32];
    vkGetPhysicalDeviceQueueFamilyProperties(physical,&families,queues);
    for(uint32_t i=0;i<families && i<32;i++) if(queues[i].queueCount && (queues[i].queueFlags&VK_QUEUE_COMPUTE_BIT)){family=i;break;}
    if(family==UINT32_MAX){fputs("FAIL: no compute queue\n",stderr);goto cleanup;}
    float priority=1;
    VkDeviceQueueCreateInfo qc={.sType=VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,.queueFamilyIndex=family,.queueCount=1,.pQueuePriorities=&priority};
    VkDeviceCreateInfo dc={.sType=VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,.queueCreateInfoCount=1,.pQueueCreateInfos=&qc};
    VK_OK(vkCreateDevice(physical,&dc,NULL,&device));
    VkQueue queue;vkGetDeviceQueue(device,family,0,&queue);
    VkBufferCreateInfo bc={.sType=VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,.size=64,.usage=VK_BUFFER_USAGE_STORAGE_BUFFER_BIT,.sharingMode=VK_SHARING_MODE_EXCLUSIVE};
    VK_OK(vkCreateBuffer(device,&bc,NULL,&buffer));
    VkMemoryRequirements requirements;vkGetBufferMemoryRequirements(device,buffer,&requirements);
    VkPhysicalDeviceMemoryProperties props;vkGetPhysicalDeviceMemoryProperties(physical,&props);
    uint32_t memtype=UINT32_MAX;
    for(uint32_t i=0;i<props.memoryTypeCount;i++) if((requirements.memoryTypeBits&(1u<<i)) &&
      (props.memoryTypes[i].propertyFlags&(VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT|VK_MEMORY_PROPERTY_HOST_COHERENT_BIT))==(VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT|VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)){memtype=i;break;}
    if(memtype==UINT32_MAX){fputs("FAIL: no host-coherent memory\n",stderr);goto cleanup;}
    VkMemoryAllocateInfo ma={.sType=VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,.allocationSize=requirements.size,.memoryTypeIndex=memtype};
    VK_OK(vkAllocateMemory(device,&ma,NULL,&memory));VK_OK(vkBindBufferMemory(device,buffer,memory,0));
    VK_OK(vkMapMemory(device,memory,0,64,0,&mapped));
    for(uint32_t i=0;i<16;i++)((uint32_t*)mapped)[i]=i;
    VkDescriptorSetLayoutBinding binding={.binding=0,.descriptorType=VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,.descriptorCount=1,.stageFlags=VK_SHADER_STAGE_COMPUTE_BIT};
    VkDescriptorSetLayoutCreateInfo sc={.sType=VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO,.bindingCount=1,.pBindings=&binding};
    VK_OK(vkCreateDescriptorSetLayout(device,&sc,NULL,&setlayout));
    VkPipelineLayoutCreateInfo lc={.sType=VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO,.setLayoutCount=1,.pSetLayouts=&setlayout};
    VK_OK(vkCreatePipelineLayout(device,&lc,NULL,&layout));
    VkShaderModuleCreateInfo sh={.sType=VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO,.codeSize=sizeof(shader_words),.pCode=shader_words};
    VK_OK(vkCreateShaderModule(device,&sh,NULL,&shader));
    VkComputePipelineCreateInfo pc={.sType=VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO,.stage={.sType=VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,.stage=VK_SHADER_STAGE_COMPUTE_BIT,.module=shader,.pName="main"},.layout=layout};
    VK_OK(vkCreateComputePipelines(device,VK_NULL_HANDLE,1,&pc,NULL,&pipeline));
    VkDescriptorPoolSize ps={.type=VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,.descriptorCount=1};
    VkDescriptorPoolCreateInfo dp={.sType=VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO,.maxSets=1,.poolSizeCount=1,.pPoolSizes=&ps};
    VK_OK(vkCreateDescriptorPool(device,&dp,NULL,&pool));
    VkDescriptorSetAllocateInfo da={.sType=VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO,.descriptorPool=pool,.descriptorSetCount=1,.pSetLayouts=&setlayout};
    VkDescriptorSet set;VK_OK(vkAllocateDescriptorSets(device,&da,&set));
    VkDescriptorBufferInfo bi={.buffer=buffer,.offset=0,.range=64};
    VkWriteDescriptorSet write={.sType=VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET,.dstSet=set,.dstBinding=0,.descriptorCount=1,.descriptorType=VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,.pBufferInfo=&bi};
    vkUpdateDescriptorSets(device,1,&write,0,NULL);
    VkCommandPoolCreateInfo cp={.sType=VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,.queueFamilyIndex=family};
    VK_OK(vkCreateCommandPool(device,&cp,NULL,&commandpool));
    VkCommandBufferAllocateInfo ca={.sType=VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,.commandPool=commandpool,.level=VK_COMMAND_BUFFER_LEVEL_PRIMARY,.commandBufferCount=1};
    VkCommandBuffer command;VK_OK(vkAllocateCommandBuffers(device,&ca,&command));
    VkCommandBufferBeginInfo begin={.sType=VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
    VK_OK(vkBeginCommandBuffer(command,&begin));
    vkCmdBindPipeline(command,VK_PIPELINE_BIND_POINT_COMPUTE,pipeline);
    vkCmdBindDescriptorSets(command,VK_PIPELINE_BIND_POINT_COMPUTE,layout,0,1,&set,0,NULL);
    vkCmdDispatch(command,1,1,1);
    VkMemoryBarrier barrier={.sType=VK_STRUCTURE_TYPE_MEMORY_BARRIER,.srcAccessMask=VK_ACCESS_SHADER_WRITE_BIT,.dstAccessMask=VK_ACCESS_HOST_READ_BIT};
    vkCmdPipelineBarrier(command,VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,VK_PIPELINE_STAGE_HOST_BIT,0,1,&barrier,0,NULL,0,NULL);
    VK_OK(vkEndCommandBuffer(command));
    VkSubmitInfo submit={.sType=VK_STRUCTURE_TYPE_SUBMIT_INFO,.commandBufferCount=1,.pCommandBuffers=&command};
    VK_OK(vkQueueSubmit(queue,1,&submit,VK_NULL_HANDLE));VK_OK(vkQueueWaitIdle(queue));
    for(uint32_t i=0;i<16;i++)if(((uint32_t*)mapped)[i]!=i+1){fprintf(stderr,"FAIL: value %u differs\n",i);goto cleanup;}
    puts("PASS: PowerVR BXM-4-64 executed a Vulkan compute shader; results verified");result=0;
cleanup:
    if(device)vkDeviceWaitIdle(device);
    if(mapped)vkUnmapMemory(device,memory);
    if(commandpool)vkDestroyCommandPool(device,commandpool,NULL);
    if(pool)vkDestroyDescriptorPool(device,pool,NULL);
    if(pipeline)vkDestroyPipeline(device,pipeline,NULL);
    if(shader)vkDestroyShaderModule(device,shader,NULL);
    if(layout)vkDestroyPipelineLayout(device,layout,NULL);
    if(setlayout)vkDestroyDescriptorSetLayout(device,setlayout,NULL);
    if(buffer)vkDestroyBuffer(device,buffer,NULL);
    if(memory)vkFreeMemory(device,memory,NULL);
    if(device)vkDestroyDevice(device,NULL);
    if(instance)vkDestroyInstance(instance,NULL);
    return result;
}
