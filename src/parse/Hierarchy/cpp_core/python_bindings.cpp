// https://pybind11.readthedocs.io/en/stable/classes.html
// https://pybind11.readthedocs.io/en/stable/advanced/exceptions.html
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/stl/filesystem.h>

#include "hierarchy_parser.hpp"

namespace py = pybind11;
using namespace arxiv::parse;

PYBIND11_MODULE(_hierarchy_native, module) {
    module.doc() = "Native LaTeX hierarchy parser";
    py::register_local_exception<nlohmann::json::exception>(module, "MappingError", PyExc_ValueError);

    py::class_<Element>(module, "Element")
        .def_readonly("element_id", &Element::element_id)
        .def_readonly("arxiv_id", &Element::arxiv_id)
        .def_readonly("kind", &Element::kind)
        .def_readonly("content", &Element::content);

    py::class_<Hierarchy>(module, "Hierarchy")
        .def_readonly("arxiv_id", &Hierarchy::arxiv_id)
        .def_readonly("version", &Hierarchy::version)
        .def_readonly("element_id", &Hierarchy::element_id)
        .def_readonly("parent_id", &Hierarchy::parent_id);

    py::class_<Diagnostic>(module, "Diagnostic")
        .def_readonly("code", &Diagnostic::code)
        .def_readonly("offset", &Diagnostic::offset)
        .def_readonly("message", &Diagnostic::message)
        .def_readonly("source", &Diagnostic::source);

    py::class_<ParseResult>(module, "ParseResult")
        .def_readonly("elements", &ParseResult::elements)
        .def_readonly("hierarchy", &ParseResult::hierarchy)
        .def_readonly("diagnostics", &ParseResult::diagnostics)
        .def_readonly("ordered_children", &ParseResult::ordered_children)
        .def_property_readonly("complete", &ParseResult::complete);

    py::class_<HierarchyParser>(module, "HierarchyParser")
        .def(py::init<std::string, int, const std::filesystem::path&>(),
             py::arg("arxiv_id"), py::arg("version"), py::arg("mapping_path"))
        .def("parse", &HierarchyParser::parse, py::arg("latex"),
             py::call_guard<py::gil_scoped_release>());
}
