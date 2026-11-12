cmake_minimum_required(VERSION 3.18)
project(arxiv_hierarchy LANGUAGES CXX)

find_package(nlohmann_json 3.11 REQUIRED)
find_package(OpenSSL REQUIRED COMPONENTS Crypto)

add_library(arxiv_hierarchy hierarchy_parser.cpp)
set_target_properties(arxiv_hierarchy PROPERTIES POSITION_INDEPENDENT_CODE ON)
target_compile_features(arxiv_hierarchy PUBLIC cxx_std_17)
target_include_directories(arxiv_hierarchy PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(arxiv_hierarchy PUBLIC nlohmann_json::nlohmann_json PRIVATE OpenSSL::Crypto)
target_compile_options(arxiv_hierarchy PRIVATE -Wall -Wextra -Wpedantic)

option(BUILD_PYTHON_BINDINGS "Build the CPython extension" OFF)
if(BUILD_PYTHON_BINDINGS)
    # https://pybind11.readthedocs.io/en/stable/compiling.html
    find_package(Python3 REQUIRED COMPONENTS Interpreter Development.Module)
    set(PYBIND11_FINDPYTHON ON)
    find_package(pybind11 3.0 CONFIG REQUIRED)
    pybind11_add_module(_hierarchy_native python_bindings.cpp)
    target_link_libraries(_hierarchy_native PRIVATE arxiv_hierarchy)
    target_compile_options(_hierarchy_native PRIVATE -Wall -Wextra -Wpedantic)
    set_target_properties(_hierarchy_native PROPERTIES
        LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
        RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/..")
endif()

include(CTest)
if(BUILD_TESTING)
    add_executable(test_hierarchy_parser test_hierarchy_parser.cpp)
    target_link_libraries(test_hierarchy_parser PRIVATE arxiv_hierarchy)
    target_compile_definitions(test_hierarchy_parser PRIVATE
        MAPPING_PATH="${CMAKE_CURRENT_SOURCE_DIR}/../mapping.json")
    add_test(NAME hierarchy_parser COMMAND test_hierarchy_parser)
endif()
