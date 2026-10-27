/* Declarations shared by the stub NI Vision and NI-IMAQdx libraries. */

#include <stdint.h>

/* A 16-bit image, the only type that the stubs make. */
typedef struct Image {
    int type;
    int width;
    int height;
    uint16_t *pixels;
} Image;

#define IMAQ_IMAGE_U16 7

/* Defined in nivision.c. Set the image size, returning 0 on failure. */
int stub_resize_image(Image *image, int width, int height);
