add_library(usermod_epaper INTERFACE)

target_sources(usermod_epaper INTERFACE
    ${CMAKE_CURRENT_LIST_DIR}/modepaper.cpp
    ${CMAKE_CURRENT_LIST_DIR}/EpaperService.cpp
)

target_include_directories(usermod_epaper INTERFACE
    ${CMAKE_CURRENT_LIST_DIR}
)

target_compile_options(usermod_epaper INTERFACE
    -fno-exceptions
    -fno-rtti
)

target_link_libraries(usermod INTERFACE
    usermod_epaper
)
