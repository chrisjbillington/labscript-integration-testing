/* A stub of the NI-IMAQdx library with the functions that labscript-devices' IMAQdx
   module calls. It has one camera, with an attribute of each type. Pixel (x, y) of the
   nth frame since the acquisition started is (10000 n + 100 y + x) mod 65536. An
   acquisition that is not continuous has as many frames as buffers, after which
   IMAQdxGrab() times out after 0.1 s. */

#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include "stub.h"

#define STRING_LENGTH 512
#define SESSION 1
#define SERIAL_NUMBER 0x1234ABCDULL

enum { U32, I64, F64, STRING, ENUM, BOOL, COMMAND };
enum { VALUE_U32, VALUE_I64, VALUE_F64, VALUE_STRING, VALUE_ENUM_ITEM, VALUE_BOOL };
enum { SIMPLE = 0x1000, INTERMEDIATE = 0x2000, ADVANCED = 0x4000 };
enum {
    ERROR_INVALID_PARAMETER = 0xBFF69002,
    ERROR_CAMERA_NOT_FOUND = 0xBFF69009,
    ERROR_CAMERA_RUNNING = 0xBFF6900D,
    ERROR_CAMERA_NOT_RUNNING = 0xBFF6900E,
    ERROR_ATTRIBUTE_NOT_SUPPORTED = 0xBFF6900F,
    ERROR_ATTRIBUTE_NOT_SETTABLE = 0xBFF69010,
    ERROR_ATTRIBUTE_NOT_READABLE = 0xBFF69011,
    ERROR_ATTRIBUTE_OUT_OF_RANGE = 0xBFF69012,
    ERROR_TIMEOUT = 0xBFF6901B,
    ERROR_INVALID_ATTRIBUTE_TYPE = 0xBFF69023,
};

typedef struct {
    uint32_t Type, Version, Flags, SerialNumberHi, SerialNumberLo, BusType;
    char InterfaceName[STRING_LENGTH], VendorName[STRING_LENGTH],
        ModelName[STRING_LENGTH], CameraFileName[STRING_LENGTH],
        CameraAttributeURL[STRING_LENGTH];
} IMAQdxCameraInformation;

typedef struct {
    uint32_t Type, Readable, Writable;
    char Name[STRING_LENGTH];
} IMAQdxAttributeInformation;

typedef struct {
    uint32_t Value, Reserved;
    char Name[STRING_LENGTH];
} IMAQdxEnumItem;

typedef struct {
    const char *name;
    uint32_t type, readable, writable, visibility;
    uint32_t u32;
    int64_t i64;
    double f64;
    char string[STRING_LENGTH];
    const IMAQdxEnumItem *items; /* An enumeration's items; u32 is the index */
} Attribute;

static const IMAQdxEnumItem PIXEL_FORMATS[] = {{0x01080001, 0, "Mono8"}, {0x01100007, 0, "Mono16"}, {0}};
static const IMAQdxEnumItem TRIGGER_MODES[] = {{0, 0, "Off"}, {1, 0, "On"}, {0}};

static Attribute attributes[] = {
    {"CameraAttributes::ImageFormatControl::Width", U32, 1, 1, SIMPLE, .u32 = 32},
    {"CameraAttributes::ImageFormatControl::Height", U32, 1, 1, SIMPLE, .u32 = 24},
    {"CameraAttributes::ImageFormatControl::OffsetX", I64, 1, 1, INTERMEDIATE, .i64 = 0},
    {"CameraAttributes::ImageFormatControl::PixelFormat", ENUM, 1, 1, SIMPLE, .u32 = 1, .items = PIXEL_FORMATS},
    {"CameraAttributes::ImageFormatControl::ReverseX", BOOL, 1, 1, INTERMEDIATE, .u32 = 0},
    {"CameraAttributes::AcquisitionControl::ExposureTime", F64, 1, 1, SIMPLE, .f64 = 1000.0},
    {"CameraAttributes::AcquisitionControl::TriggerMode", ENUM, 1, 1, SIMPLE, .u32 = 0, .items = TRIGGER_MODES},
    {"CameraAttributes::DeviceControl::DeviceModelName", STRING, 1, 0, SIMPLE, .string = "IMAQdx stub"},
    {"CameraAttributes::DeviceControl::DeviceUserID", STRING, 1, 1, ADVANCED, .string = ""},
    {"CameraAttributes::DeviceControl::DeviceReset", COMMAND, 0, 1, ADVANCED},
};
#define N_ATTRIBUTES (sizeof(attributes) / sizeof(attributes[0]))

static int is_open = 0, configured = 0, running = 0, continuous = 0;
static uint32_t buffer_count = 0, frame = 0;

static Attribute *find(uint32_t id, const char *name) {
    for (size_t i = 0; id == SESSION && is_open && name && i < N_ATTRIBUTES; i++) {
        if (!strcmp(attributes[i].name, name)) return &attributes[i];
    }
    return NULL;
}

uint32_t IMAQdxGetErrorString(uint32_t error, char *message, uint32_t length) {
    snprintf(message, length, "Stub IMAQdx error 0x%08X", error);
    return 0;
}

uint32_t IMAQdxEnumerateCameras(IMAQdxCameraInformation *cameras, uint32_t *count, uint32_t connectedOnly) {
    if (!count) return ERROR_INVALID_PARAMETER;
    if (cameras && *count >= 1) {
        memset(cameras, 0, sizeof(*cameras));
        cameras->SerialNumberHi = SERIAL_NUMBER >> 32;
        cameras->SerialNumberLo = SERIAL_NUMBER & 0xFFFFFFFF;
        strcpy(cameras->InterfaceName, "cam0");
        strcpy(cameras->VendorName, "labscript-integration-testing");
        strcpy(cameras->ModelName, "IMAQdx stub");
    }
    *count = 1;
    return 0;
}

uint32_t IMAQdxOpenCamera(const char *name, uint32_t mode, uint32_t *id) {
    if (!name || strcmp(name, "cam0") || mode != 0) return ERROR_CAMERA_NOT_FOUND;
    is_open = 1;
    *id = SESSION;
    return 0;
}

uint32_t IMAQdxCloseCamera(uint32_t id) {
    if (id != SESSION || !is_open) return ERROR_INVALID_PARAMETER;
    is_open = configured = running = 0;
    return 0;
}

uint32_t IMAQdxConfigureAcquisition(uint32_t id, uint32_t is_continuous, uint32_t bufferCount) {
    if (id != SESSION || !is_open || bufferCount == 0) return ERROR_INVALID_PARAMETER;
    if (configured) return ERROR_CAMERA_RUNNING;
    configured = 1;
    continuous = is_continuous;
    buffer_count = bufferCount;
    return 0;
}

uint32_t IMAQdxStartAcquisition(uint32_t id) {
    if (id != SESSION || !configured) return ERROR_CAMERA_NOT_RUNNING;
    running = 1;
    frame = 0;
    return 0;
}

uint32_t IMAQdxStopAcquisition(uint32_t id) {
    if (id != SESSION || !running) return ERROR_CAMERA_NOT_RUNNING;
    running = 0;
    return 0;
}

uint32_t IMAQdxUnconfigureAcquisition(uint32_t id) {
    if (id != SESSION || running || !configured) return ERROR_CAMERA_RUNNING;
    configured = 0;
    return 0;
}

static uint32_t fill(Image *image, uint32_t n) {
    int width = attributes[0].u32, height = attributes[1].u32;
    if (!stub_resize_image(image, width, height)) return ERROR_INVALID_PARAMETER;
    for (int y = 0; y < height; y++)
        for (int x = 0; x < width; x++)
            image->pixels[y * width + x] = (uint16_t)(10000 * n + 100 * y + x);
    return 0;
}

uint32_t IMAQdxGrab(uint32_t id, Image *image, uint32_t waitForNextBuffer, uint32_t *actualBufferNumber) {
    if (id != SESSION || !running) return ERROR_CAMERA_NOT_RUNNING;
    if (!continuous && frame >= buffer_count) {
        usleep(100000);
        return ERROR_TIMEOUT;
    }
    uint32_t error = fill(image, frame);
    if (!error && actualBufferNumber) *actualBufferNumber = frame;
    frame += !error;
    return error;
}

uint32_t IMAQdxSnap(uint32_t id, Image *image) {
    if (id != SESSION || !is_open) return ERROR_INVALID_PARAMETER;
    if (configured) return ERROR_CAMERA_RUNNING;
    return fill(image, 0);
}

uint32_t IMAQdxGetAttributeType(uint32_t id, const char *name, uint32_t *type) {
    Attribute *a = find(id, name);
    if (!a) return ERROR_ATTRIBUTE_NOT_SUPPORTED;
    *type = a->type;
    return 0;
}

uint32_t IMAQdxGetAttribute(uint32_t id, const char *name, uint32_t valueType, void *value) {
    Attribute *a = find(id, name);
    if (!a) return ERROR_ATTRIBUTE_NOT_SUPPORTED;
    if (!a->readable) return ERROR_ATTRIBUTE_NOT_READABLE;
    if (a->type == U32 && valueType == VALUE_U32) *(uint32_t *)value = a->u32;
    else if (a->type == I64 && valueType == VALUE_I64) *(int64_t *)value = a->i64;
    else if (a->type == F64 && valueType == VALUE_F64) *(double *)value = a->f64;
    else if (a->type == BOOL && valueType == VALUE_BOOL) *(uint32_t *)value = a->u32;
    else if (a->type == STRING && valueType == VALUE_STRING) strcpy(value, a->string);
    else if (a->type == ENUM && valueType == VALUE_ENUM_ITEM) *(IMAQdxEnumItem *)value = a->items[a->u32];
    else return ERROR_INVALID_ATTRIBUTE_TYPE;
    return 0;
}

static uint32_t set_enum(Attribute *a, uint32_t value, const char *name) {
    for (uint32_t i = 0; a->items[i].Name[0]; i++) {
        if (name ? !strcmp(a->items[i].Name, name) : a->items[i].Value == value) {
            a->u32 = i;
            return 0;
        }
    }
    return ERROR_ATTRIBUTE_OUT_OF_RANGE;
}

uint32_t IMAQdxSetAttribute(uint32_t id, const char *name, uint32_t valueType, ...) {
    Attribute *a = find(id, name);
    if (!a) return ERROR_ATTRIBUTE_NOT_SUPPORTED;
    if (!a->writable || running) return ERROR_ATTRIBUTE_NOT_SETTABLE;
    uint32_t error = 0;
    va_list args;
    va_start(args, valueType);
    if (a->type == U32 && valueType == VALUE_U32) a->u32 = va_arg(args, uint32_t);
    else if (a->type == I64 && valueType == VALUE_I64) a->i64 = va_arg(args, int64_t);
    else if (a->type == F64 && valueType == VALUE_F64) a->f64 = va_arg(args, double);
    else if (a->type == BOOL && valueType == VALUE_BOOL) a->u32 = va_arg(args, uint32_t) != 0;
    else if (a->type == STRING && valueType == VALUE_STRING)
        snprintf(a->string, STRING_LENGTH, "%s", va_arg(args, const char *));
    else if (a->type == ENUM && valueType == VALUE_U32) error = set_enum(a, va_arg(args, uint32_t), NULL);
    else if (a->type == ENUM && valueType == VALUE_STRING) error = set_enum(a, 0, va_arg(args, const char *));
    else error = ERROR_INVALID_ATTRIBUTE_TYPE;
    va_end(args);
    return error;
}

uint32_t IMAQdxEnumerateAttributes2(uint32_t id, IMAQdxAttributeInformation *list, uint32_t *count,
                                    const char *root, uint32_t visibility) {
    if (id != SESSION || !is_open || !count || !root) return ERROR_INVALID_PARAMETER;
    uint32_t n = 0;
    for (size_t i = 0; i < N_ATTRIBUTES; i++) {
        Attribute *a = &attributes[i];
        if (a->visibility > visibility || strncmp(a->name, root, strlen(root))) continue;
        if (list && n < *count) {
            list[n].Type = a->type;
            list[n].Readable = a->readable;
            list[n].Writable = a->writable;
            strcpy(list[n].Name, a->name);
        }
        n++;
    }
    *count = n;
    return 0;
}
