cmake_minimum_required(VERSION 3.20)

set(PLUGIN_NAME "HTML2PDF" CACHE STRING "Plugin name")
project(${PLUGIN_NAME} LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_C_STANDARD 17)

set(SDK_DIR "${CMAKE_SOURCE_DIR}/../4D-Plugin-SDK/4D Plugin API")

if(WIN32)
    set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>" CACHE STRING "" FORCE)
endif()

# --- Third-party libraries ---
# litehtml uses constexpr with std::abs which MSVC C++17 rejects (C3615).
# Build litehtml as C++20 on MSVC to work around this.
set(LITEHTML_DIR "${CMAKE_SOURCE_DIR}/../deps/litehtml")
add_subdirectory("${LITEHTML_DIR}" "${CMAKE_BINARY_DIR}/litehtml")
if(MSVC)
    # Patch litehtml pixel_type.h: remove constexpr from operators using std::abs
    # MSVC does not consider std::abs constexpr even in C++20
    file(READ "${LITEHTML_DIR}/include/litehtml/pixel_type.h" _pixel_src)
    string(REPLACE "constexpr bool operator==" "inline bool operator==" _pixel_src "${_pixel_src}")
    string(REPLACE "constexpr bool operator!=" "inline bool operator!=" _pixel_src "${_pixel_src}")
    string(REPLACE "constexpr bool operator<" "inline bool operator<" _pixel_src "${_pixel_src}")
    string(REPLACE "constexpr bool operator>" "inline bool operator>" _pixel_src "${_pixel_src}")
    string(REPLACE "constexpr bool operator<=" "inline bool operator<=" _pixel_src "${_pixel_src}")
    string(REPLACE "constexpr bool operator>=" "inline bool operator>=" _pixel_src "${_pixel_src}")
    file(WRITE "${LITEHTML_DIR}/include/litehtml/pixel_type.h" "${_pixel_src}")
endif()

set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
set(LIBHPDF_EXAMPLES OFF CACHE BOOL "" FORCE)
set(LIBHARU_DIR "${CMAKE_SOURCE_DIR}/../deps/libharu")
add_subdirectory("${LIBHARU_DIR}" "${CMAKE_BINARY_DIR}/libharu/include")

# --- Plugin source files ---
set(PLUGIN_SOURCES
    ${PLUGIN_NAME}-4dplugin.cpp
    pdf_container.cpp
    stb_impl.c
    "${SDK_DIR}/4DPluginAPI.c"
)

set(PLUGIN_HEADERS
    ${PLUGIN_NAME}-4dplugin.h
    pdf_container.h
    "${SDK_DIR}/4DPluginAPI.h"
    "${SDK_DIR}/EntryPoints.h"
    "${SDK_DIR}/PublicTypes.h"
    "${SDK_DIR}/PrivateTypes.h"
    "${SDK_DIR}/Flags.h"
)

set(PLUGIN_RESOURCES manifest.json constants.xlf)

if(APPLE)
    add_library(${PLUGIN_NAME} MODULE ${PLUGIN_SOURCES} ${PLUGIN_HEADERS} ${PLUGIN_RESOURCES})
    set_target_properties(${PLUGIN_NAME} PROPERTIES
        BUNDLE TRUE
        BUNDLE_EXTENSION "bundle"
        MACOSX_BUNDLE_INFO_PLIST "${CMAKE_SOURCE_DIR}/Info.plist.in"
        MACOSX_BUNDLE_GUI_IDENTIFIER "com.4d.${PLUGIN_NAME}"
        MACOSX_BUNDLE_BUNDLE_VERSION "1.0"
        MACOSX_BUNDLE_SHORT_VERSION_STRING "1.0"
    )
    set_source_files_properties(${PLUGIN_RESOURCES} PROPERTIES MACOSX_PACKAGE_LOCATION Resources)
    find_library(COREGRAPHICS_FRAMEWORK CoreGraphics REQUIRED)
    target_link_libraries(${PLUGIN_NAME} PRIVATE ${COREGRAPHICS_FRAMEWORK} litehtml hpdf)
    set_target_properties(${PLUGIN_NAME} PROPERTIES
        LIBRARY_OUTPUT_DIRECTORY "${CMAKE_SOURCE_DIR}/${PLUGIN_NAME}-test/Plugins"
        LIBRARY_OUTPUT_DIRECTORY_DEBUG "${CMAKE_SOURCE_DIR}/${PLUGIN_NAME}-test/Plugins"
        LIBRARY_OUTPUT_DIRECTORY_RELEASE "${CMAKE_SOURCE_DIR}/${PLUGIN_NAME}-test/Plugins"
    )
elseif(WIN32)
    add_library(${PLUGIN_NAME} SHARED ${PLUGIN_SOURCES} ${PLUGIN_HEADERS})
    set_target_properties(${PLUGIN_NAME} PROPERTIES
        SUFFIX ".4DX"
        LINK_FLAGS "/DEF:\"${SDK_DIR}/4DPluginAPI.def\""
    )
    set_property(TARGET ${PLUGIN_NAME} PROPERTY
        MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>"
    )
    set(PLUGIN_OUT_DIR "${CMAKE_SOURCE_DIR}/${PLUGIN_NAME}-test/Plugins/${PLUGIN_NAME}/Contents/Windows64")
    set(RESOURCE_OUT_DIR "${CMAKE_SOURCE_DIR}/${PLUGIN_NAME}-test/Plugins/${PLUGIN_NAME}/Contents/Resources")
    set_target_properties(${PLUGIN_NAME} PROPERTIES
        RUNTIME_OUTPUT_DIRECTORY "${PLUGIN_OUT_DIR}"
        RUNTIME_OUTPUT_DIRECTORY_DEBUG "${PLUGIN_OUT_DIR}"
        RUNTIME_OUTPUT_DIRECTORY_RELEASE "${PLUGIN_OUT_DIR}"
    )
    target_link_libraries(${PLUGIN_NAME} PRIVATE litehtml hpdf)
    add_custom_command(TARGET ${PLUGIN_NAME} POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E make_directory "${RESOURCE_OUT_DIR}"
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "${CMAKE_SOURCE_DIR}/manifest.json"
            "${CMAKE_SOURCE_DIR}/constants.xlf"
            "${RESOURCE_OUT_DIR}"
    )
endif()

target_include_directories(${PLUGIN_NAME} PRIVATE
    "${SDK_DIR}"
    "${LITEHTML_DIR}/include"
    "${LIBHARU_DIR}/include"
    "${CMAKE_BINARY_DIR}/libharu/include/include"
)
set_source_files_properties("${SDK_DIR}/4DPluginAPI.c" PROPERTIES LANGUAGE CXX)
target_compile_definitions(${PLUGIN_NAME} PRIVATE UNICODE _UNICODE)
