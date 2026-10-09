add_library(usermod_tft INTERFACE)

target_sources(usermod_tft INTERFACE
    ${CMAKE_CURRENT_LIST_DIR}/modtft.cpp
    ${CMAKE_CURRENT_LIST_DIR}/TftService.cpp
)

target_include_directories(usermod_tft INTERFACE ${CMAKE_CURRENT_LIST_DIR})
target_compile_options(usermod_tft INTERFACE -fno-exceptions -fno-rtti)
target_link_libraries(usermod INTERFACE usermod_tft)
