// Minimal nativecan MicroPython module.
//
// Keep bindings in the interpreter context.  The future CAN worker must not
// call MicroPython APIs or access Python-owned memory from its FreeRTOS task.
extern "C" {
#include "py/runtime.h"
}

static mp_obj_t nativecan_hello(void) {
    static constexpr char message[] = "nativecan module loaded";
    return mp_obj_new_str(message, sizeof(message) - 1);
}
static MP_DEFINE_CONST_FUN_OBJ_0(nativecan_hello_obj, nativecan_hello);

static const mp_rom_map_elem_t nativecan_module_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_nativecan) },
    { MP_ROM_QSTR(MP_QSTR_hello), MP_ROM_PTR(&nativecan_hello_obj) },
};
static MP_DEFINE_CONST_DICT(nativecan_module_globals, nativecan_module_globals_table);

extern "C" const mp_obj_module_t mp_module_nativecan = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&nativecan_module_globals,
};

MP_REGISTER_MODULE(MP_QSTR_nativecan, mp_module_nativecan);
