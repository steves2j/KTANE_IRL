// MicroPython bindings for the external MCP2518FD CAN controller.
//
// Keep bindings in the interpreter context.  The future CAN worker must not
// call MicroPython APIs or access Python-owned memory from its FreeRTOS task.
extern "C" {
#include "py/runtime.h"
}

#include "CanService.hpp"

static mp_obj_t mcp2518_hello(void) {
    static constexpr char message[] = "mcp2518 module loaded";
    return mp_obj_new_str(message, sizeof(message) - 1);
}
static MP_DEFINE_CONST_FUN_OBJ_0(mcp2518_hello_obj, mcp2518_hello);

static mp_obj_t mcp2518_start(void) {
    return mp_obj_new_bool(can_service().start());
}
static MP_DEFINE_CONST_FUN_OBJ_0(mcp2518_start_obj, mcp2518_start);

static mp_obj_t mcp2518_status(void) {
    const CanServiceStatus status = can_service().status();
    mp_obj_t dict = mp_obj_new_dict(10);
    mp_obj_dict_store(dict, MP_OBJ_NEW_QSTR(MP_QSTR_started), mp_obj_new_bool(status.started));
    mp_obj_dict_store(dict, MP_OBJ_NEW_QSTR(MP_QSTR_spi_responding), mp_obj_new_bool(status.spi_responding));
    mp_obj_dict_store(dict, MP_OBJ_NEW_QSTR(MP_QSTR_initialized), mp_obj_new_bool(status.initialized));
    mp_obj_dict_store(dict, MP_OBJ_NEW_QSTR(MP_QSTR_loopback), mp_obj_new_bool(status.loopback));
    mp_obj_dict_store(dict, MP_OBJ_NEW_QSTR(MP_QSTR_device_id), mp_obj_new_int_from_uint(status.device_id));
    mp_obj_dict_store(dict, MP_OBJ_NEW_QSTR(MP_QSTR_controller_config), mp_obj_new_int_from_uint(status.controller_config));
    mp_obj_dict_store(dict, MP_OBJ_NEW_QSTR(MP_QSTR_oscillator), mp_obj_new_int_from_uint(status.oscillator));
    mp_obj_dict_store(dict, MP_OBJ_NEW_QSTR(MP_QSTR_tx_dropped), mp_obj_new_int_from_uint(status.tx_dropped));
    mp_obj_dict_store(dict, MP_OBJ_NEW_QSTR(MP_QSTR_rx_dropped), mp_obj_new_int_from_uint(status.rx_dropped));
    mp_obj_dict_store(dict, MP_OBJ_NEW_QSTR(MP_QSTR_error), mp_obj_new_int(status.last_error));
    mp_obj_dict_store(dict, MP_OBJ_NEW_QSTR(MP_QSTR_worker_core), mp_obj_new_int(1));
    return dict;
}
static MP_DEFINE_CONST_FUN_OBJ_0(mcp2518_status_obj, mcp2518_status);

static mp_obj_t mcp2518_send(mp_obj_t id_obj, mp_obj_t data_obj) {
    CanFrame frame{};
    frame.identifier = mp_obj_get_int_truncated(id_obj);
    mp_buffer_info_t data;
    mp_get_buffer_raise(data_obj, &data, MP_BUFFER_READ);
    if (data.len > sizeof(frame.data)) mp_raise_ValueError(MP_ERROR_TEXT("CAN data is limited to 64 bytes"));
    frame.length = data.len;
    memcpy(frame.data, data.buf, data.len);
    return mp_obj_new_bool(can_service().enqueue(frame));
}
static MP_DEFINE_CONST_FUN_OBJ_2(mcp2518_send_obj, mcp2518_send);

static mp_obj_t mcp2518_recv(void) {
    CanFrame frame{};
    if (!can_service().dequeue(&frame)) return mp_const_none;
    mp_obj_t items[2] = {mp_obj_new_int_from_uint(frame.identifier), mp_obj_new_bytes(frame.data, frame.length)};
    return mp_obj_new_tuple(2, items);
}
static MP_DEFINE_CONST_FUN_OBJ_0(mcp2518_recv_obj, mcp2518_recv);

static mp_obj_t mcp2518_set_mode(mp_obj_t mode_obj) {
    size_t length;
    const char *mode = mp_obj_str_get_data(mode_obj, &length);
    bool loopback;
    if (length == 8 && memcmp(mode, "loopback", 8) == 0) {
        loopback = true;
    } else if (length == 6 && memcmp(mode, "normal", 6) == 0) {
        loopback = false;
    } else {
        mp_raise_ValueError(MP_ERROR_TEXT("mode must be 'loopback' or 'normal'"));
    }
    return mp_obj_new_bool(can_service().set_loopback(loopback));
}
static MP_DEFINE_CONST_FUN_OBJ_1(mcp2518_set_mode_obj, mcp2518_set_mode);

static const mp_rom_map_elem_t mcp2518_module_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_mcp2518) },
    { MP_ROM_QSTR(MP_QSTR_hello), MP_ROM_PTR(&mcp2518_hello_obj) },
    { MP_ROM_QSTR(MP_QSTR_start), MP_ROM_PTR(&mcp2518_start_obj) },
    { MP_ROM_QSTR(MP_QSTR_status), MP_ROM_PTR(&mcp2518_status_obj) },
    { MP_ROM_QSTR(MP_QSTR_send), MP_ROM_PTR(&mcp2518_send_obj) },
    { MP_ROM_QSTR(MP_QSTR_recv), MP_ROM_PTR(&mcp2518_recv_obj) },
    { MP_ROM_QSTR(MP_QSTR_set_mode), MP_ROM_PTR(&mcp2518_set_mode_obj) },
};
static MP_DEFINE_CONST_DICT(mcp2518_module_globals, mcp2518_module_globals_table);

extern "C" const mp_obj_module_t mp_module_mcp2518 = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&mcp2518_module_globals,
};

MP_REGISTER_MODULE(MP_QSTR_mcp2518, mp_module_mcp2518);
