/* Controlled device enumeration for rejection tests; executes no GPU work. */
#include <vulkan/vulkan.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
VKAPI_ATTR VkResult VKAPI_CALL vkCreateInstance(const VkInstanceCreateInfo *info, const VkAllocationCallbacks *alloc, VkInstance *instance) {
    (void)info; (void)alloc; *instance=(VkInstance)(uintptr_t)1; return VK_SUCCESS;
}
VKAPI_ATTR VkResult VKAPI_CALL vkEnumeratePhysicalDevices(VkInstance instance, uint32_t *count, VkPhysicalDevice *devices) {
    (void)instance;
    if (devices && *count) devices[0]=(VkPhysicalDevice)(uintptr_t)2;
    *count=1; return VK_SUCCESS;
}
VKAPI_ATTR void VKAPI_CALL vkGetPhysicalDeviceProperties(VkPhysicalDevice device, VkPhysicalDeviceProperties *props) {
    (void)device; memset(props,0,sizeof(*props));
    const char *mode=getenv("VK_TEST_MODE");
    props->deviceType=(mode && strcmp(mode,"cpu")==0) ? VK_PHYSICAL_DEVICE_TYPE_CPU : VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU;
    strcpy(props->deviceName,(mode && strcmp(mode,"cpu")==0) ? "PowerVR BXM-4-64" : "Wrong hardware GPU");
}
VKAPI_ATTR void VKAPI_CALL vkDestroyInstance(VkInstance instance, const VkAllocationCallbacks *alloc) {
    (void)instance; (void)alloc;
}
