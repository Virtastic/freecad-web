cmake_minimum_required(VERSION 3.16)
project(qt_spike LANGUAGES CXX)

set(CMAKE_AUTOMOC ON)
find_package(Qt6 REQUIRED COMPONENTS Core Gui Widgets)

qt_add_executable(qt_spike main.cpp)
target_link_libraries(qt_spike PRIVATE Qt6::Core Qt6::Gui Qt6::Widgets)
