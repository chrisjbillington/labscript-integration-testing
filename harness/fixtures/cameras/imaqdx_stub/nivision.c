/* A stub of the NI Vision library with the image functions that labscript-devices'
   IMAQdx module calls. Every allocation is recorded, so that stub_live_allocations()
   can report the ones that were not disposed. */

#include <stdlib.h>
#include <string.h>
#include "stub.h"

#define ERR_NOT_IMAGE -1074396120
#define ERR_INVALID_IMAGE_TYPE -1074396080
#define ERR_OUT_OF_MEMORY -1074396159
#define MAX_ALLOCATIONS 1024

typedef struct Rect { int top, left, height, width; } Rect;

static int last_error = 0;
static void *allocations[MAX_ALLOCATIONS];
static int is_image[MAX_ALLOCATIONS];

static void *record(void *p, int image) {
    for (int i = 0; p && i < MAX_ALLOCATIONS; i++) {
        if (!allocations[i]) {
            allocations[i] = p;
            is_image[i] = image;
            return p;
        }
    }
    free(p);
    last_error = ERR_OUT_OF_MEMORY;
    return NULL;
}

static int find(const void *p, int image) {
    for (int i = 0; p && i < MAX_ALLOCATIONS; i++) {
        if (allocations[i] == p && (image < 0 || is_image[i] == image)) return i;
    }
    return -1;
}

int stub_live_allocations(void) {
    int n = 0;
    for (int i = 0; i < MAX_ALLOCATIONS; i++) n += allocations[i] != NULL;
    return n;
}

int stub_resize_image(Image *image, int width, int height) {
    if (find(image, 1) < 0) return 0;
    uint16_t *pixels = realloc(image->pixels, (size_t)width * height * 2 + 1);
    if (!pixels) return 0;
    image->pixels = pixels;
    image->width = width;
    image->height = height;
    return 1;
}

int imaqGetLastError(void) { return last_error; }

char *imaqGetErrorText(int code) {
    const char *text = code == ERR_NOT_IMAGE ? "Not an image."
                     : code == ERR_INVALID_IMAGE_TYPE ? "Invalid image type."
                     : "Stub error.";
    char *copy = record(malloc(strlen(text) + 1), 0);
    if (copy) strcpy(copy, text);
    return copy;
}

Image *imaqCreateImage(unsigned int type, int borderSize) {
    if (type != IMAQ_IMAGE_U16 || borderSize < 0) {
        last_error = ERR_INVALID_IMAGE_TYPE;
        return NULL;
    }
    Image *image = record(calloc(1, sizeof(Image)), 1);
    if (image) image->type = type;
    return image;
}

int imaqDispose(void *object) {
    int i = find(object, -1);
    if (i < 0) {
        last_error = ERR_NOT_IMAGE;
        return 0;
    }
    if (is_image[i]) free(((Image *)object)->pixels);
    free(object);
    allocations[i] = NULL;
    return 1;
}

int imaqGetBytesPerPixel(const Image *image, int *byteCount) {
    if (find(image, 1) < 0) {
        last_error = ERR_NOT_IMAGE;
        return 0;
    }
    *byteCount = 2;
    return 1;
}

void *imaqImageToArray(const Image *image, Rect rect, int *columns, int *rows) {
    if (find(image, 1) < 0 || rect.top || rect.left || !image->pixels) {
        last_error = ERR_NOT_IMAGE;
        return NULL;
    }
    size_t size = (size_t)image->width * image->height * 2;
    void *array = record(malloc(size + 1), 0);
    if (!array) return NULL;
    memcpy(array, image->pixels, size);
    *columns = image->width;
    *rows = image->height;
    return array;
}
