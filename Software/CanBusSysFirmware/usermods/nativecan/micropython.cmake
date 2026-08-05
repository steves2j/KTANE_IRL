add_library(usermod_nativecan INTERFACE)

target_sources(usermod_nativecan INTERFACE
    ${CMAKE_CURRENT_LIST_DIR}/modnativecan.cpp
    ${CMAKE_CURRENT_LIST_DIR}/CanService.cpp
)

target_include_directories(usermod_nativecan INTERFACE
    ${CMAKE_CURRENT_LIST_DIR}
)

target_compile_options(usermod_nativecan INTERFACE
    -fno-exceptions
    -fno-rtti
)

target_link_libraries(usermod INTERFACE
    usermod_nativecan
)
