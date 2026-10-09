// MicroPython bindings for the native SSD1683 / GDEY042T81 display driver.
extern "C" {
#include "py/runtime.h"
}

#include "EpaperService.hpp"

namespace {

const uint8_t *framebuffer_from_obj(mp_obj_t object, mp_buffer_info_t *buffer) {
    mp_get_buffer_raise(object, buffer, MP_BUFFER_READ);
    if (buffer->len != 15000) {
        mp_raise_ValueError(MP_ERROR_TEXT("framebuffer must be exactly 15000 bytes"));
    }
    return static_cast<const uint8_t *>(buffer->buf);
}

mp_obj_t result_or_raise(esp_err_t error) {
    if (error != ESP_OK) mp_raise_OSError(error);
    return mp_const_true;
}

mp_obj_t epaper_init(size_t count, const mp_obj_t *args) {
    const EpaperPins pins = {
        mp_obj_get_int(args[0]), // CS
        mp_obj_get_int(args[1]), // D/C
        mp_obj_get_int(args[2]), // RESET
        mp_obj_get_int(args[3]), // BUSY
        mp_obj_get_int(args[4]), // SCK
        mp_obj_get_int(args[5]), // MOSI / panel SDI
    };
    return result_or_raise(epaper_service().init(pins));
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(epaper_init_obj, 6, 6, epaper_init);

mp_obj_t epaper_detach() { return result_or_raise(epaper_service().detach()); }
static MP_DEFINE_CONST_FUN_OBJ_0(epaper_detach_obj, epaper_detach);

mp_obj_t epaper_attach() { return result_or_raise(epaper_service().attach()); }
static MP_DEFINE_CONST_FUN_OBJ_0(epaper_attach_obj, epaper_attach);

mp_obj_t epaper_full(mp_obj_t framebuffer_obj) {
    mp_buffer_info_t buffer;
    return result_or_raise(epaper_service().full_refresh(framebuffer_from_obj(framebuffer_obj, &buffer), buffer.len));
}
static MP_DEFINE_CONST_FUN_OBJ_1(epaper_full_obj, epaper_full);

mp_obj_t epaper_base_map(mp_obj_t framebuffer_obj) {
    mp_buffer_info_t buffer;
    return result_or_raise(epaper_service().set_partial_base_map(framebuffer_from_obj(framebuffer_obj, &buffer), buffer.len));
}
static MP_DEFINE_CONST_FUN_OBJ_1(epaper_base_map_obj, epaper_base_map);

mp_obj_t epaper_partial(size_t count, const mp_obj_t *args) {
    mp_buffer_info_t buffer;
    const int x = mp_obj_get_int(args[1]);
    const int y = mp_obj_get_int(args[2]);
    const int width = mp_obj_get_int(args[3]);
    const int height = mp_obj_get_int(args[4]);
    return result_or_raise(epaper_service().partial_refresh(framebuffer_from_obj(args[0], &buffer), buffer.len,
                                                            x, y, width, height));
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(epaper_partial_obj, 5, 5, epaper_partial);

mp_obj_t epaper_status() {
    const EpaperStatus status = epaper_service().status();
    mp_obj_t dict = mp_obj_new_dict(4);
    mp_obj_dict_store(dict, MP_OBJ_NEW_QSTR(MP_QSTR_bus_ready), mp_obj_new_bool(status.bus_ready));
    mp_obj_dict_store(dict, MP_OBJ_NEW_QSTR(MP_QSTR_initialized), mp_obj_new_bool(status.initialized));
    mp_obj_dict_store(dict, MP_OBJ_NEW_QSTR(MP_QSTR_busy), mp_obj_new_bool(status.busy));
    mp_obj_dict_store(dict, MP_OBJ_NEW_QSTR(MP_QSTR_error), mp_obj_new_int(status.last_error));
    return dict;
}
static MP_DEFINE_CONST_FUN_OBJ_0(epaper_status_obj, epaper_status);

const mp_rom_map_elem_t epaper_module_globals_table[] = {
    {MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_epaper)},
    {MP_ROM_QSTR(MP_QSTR_init), MP_ROM_PTR(&epaper_init_obj)},
    {MP_ROM_QSTR(MP_QSTR_detach), MP_ROM_PTR(&epaper_detach_obj)},
    {MP_ROM_QSTR(MP_QSTR_attach), MP_ROM_PTR(&epaper_attach_obj)},
    {MP_ROM_QSTR(MP_QSTR_full), MP_ROM_PTR(&epaper_full_obj)},
    {MP_ROM_QSTR(MP_QSTR_base_map), MP_ROM_PTR(&epaper_base_map_obj)},
    {MP_ROM_QSTR(MP_QSTR_partial), MP_ROM_PTR(&epaper_partial_obj)},
    {MP_ROM_QSTR(MP_QSTR_status), MP_ROM_PTR(&epaper_status_obj)},
};
MP_DEFINE_CONST_DICT(epaper_module_globals, epaper_module_globals_table);

} // namespace

extern "C" const mp_obj_module_t mp_module_epaper = {
    .base = {&mp_type_module},
    .globals = (mp_obj_dict_t *)&epaper_module_globals,
};

MP_REGISTER_MODULE(MP_QSTR_epaper, mp_module_epaper);
