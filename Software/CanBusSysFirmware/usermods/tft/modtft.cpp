extern "C" {
#include "py/runtime.h"
}
#include "TftService.hpp"

namespace {
mp_obj_t result_or_raise(esp_err_t error) { if (error != ESP_OK) mp_raise_OSError(error); return mp_const_true; }
mp_obj_t tft_init(size_t, const mp_obj_t *args) {
    const TftPins pins = {mp_obj_get_int(args[0]), mp_obj_get_int(args[1]), mp_obj_get_int(args[2]),
                          mp_obj_get_int(args[3]), mp_obj_get_int(args[4]), mp_obj_get_int(args[5])};
    return result_or_raise(tft_service().init(pins));
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(tft_init_obj, 6, 6, tft_init);
mp_obj_t tft_text(mp_obj_t text) {
    size_t length;
    const char *value = mp_obj_str_get_data(text, &length);
    (void)length;
    return result_or_raise(tft_service().draw_text(value));
}
static MP_DEFINE_CONST_FUN_OBJ_1(tft_text_obj, tft_text);
mp_obj_t tft_show_digit(mp_obj_t digit) { return result_or_raise(tft_service().show_digit(mp_obj_get_int(digit))); }
static MP_DEFINE_CONST_FUN_OBJ_1(tft_show_digit_obj, tft_show_digit);
mp_obj_t tft_status() { const TftStatus s = tft_service().status(); mp_obj_t d = mp_obj_new_dict(3); mp_obj_dict_store(d, MP_OBJ_NEW_QSTR(MP_QSTR_bus_ready), mp_obj_new_bool(s.bus_ready)); mp_obj_dict_store(d, MP_OBJ_NEW_QSTR(MP_QSTR_initialized), mp_obj_new_bool(s.initialized)); mp_obj_dict_store(d, MP_OBJ_NEW_QSTR(MP_QSTR_error), mp_obj_new_int(s.last_error)); return d; }
static MP_DEFINE_CONST_FUN_OBJ_0(tft_status_obj, tft_status);
const mp_rom_map_elem_t globals[] = {{MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_tft)}, {MP_ROM_QSTR(MP_QSTR_init), MP_ROM_PTR(&tft_init_obj)}, {MP_ROM_QSTR(MP_QSTR_text), MP_ROM_PTR(&tft_text_obj)}, {MP_ROM_QSTR(MP_QSTR_show_digit), MP_ROM_PTR(&tft_show_digit_obj)}, {MP_ROM_QSTR(MP_QSTR_status), MP_ROM_PTR(&tft_status_obj)}};
MP_DEFINE_CONST_DICT(module_globals, globals);
}
extern "C" const mp_obj_module_t mp_module_tft = {.base = {&mp_type_module}, .globals = (mp_obj_dict_t *)&module_globals};
MP_REGISTER_MODULE(MP_QSTR_tft, mp_module_tft);
