file(GLOB _pictologics_support_tests
  "${CMAKE_CURRENT_SOURCE_DIR}/../../../tests/test_*.py"
  )
foreach(_test_script IN LISTS _pictologics_support_tests)
  slicer_add_python_unittest(SCRIPT ${_test_script})
endforeach()
