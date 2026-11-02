file(GLOB _pictologics_support_tests
  "${CMAKE_CURRENT_SOURCE_DIR}/../../../tests/test_*.py"
  )
# These tests import pytest or PyYAML, which a clean Slicer does not provide.
# They run in normal-Python CI. A contract test keeps this list complete.
list(FILTER _pictologics_support_tests EXCLUDE REGEX "/test_release_workflows[.]py$")
list(FILTER _pictologics_support_tests EXCLUDE REGEX "/test_platform_constraints[.]py$")
list(FILTER _pictologics_support_tests EXCLUDE REGEX "/test_platform_contracts[.]py$")
list(FILTER _pictologics_support_tests EXCLUDE REGEX "/test_preset_catalog[.]py$")
list(FILTER _pictologics_support_tests EXCLUDE REGEX "/test_batch_soak_support[.]py$")
foreach(_test_script IN LISTS _pictologics_support_tests)
  slicer_add_python_unittest(SCRIPT ${_test_script})
endforeach()

# This fixture exercises MRML geometry and segmentation conversion APIs and
# therefore runs only inside a real Slicer process, not in the portable pytest job.
slicer_add_python_unittest(
  SCRIPT ${CMAKE_CURRENT_SOURCE_DIR}/PictologicsSlicerIntegrationTest.py
  SLICER_ARGS
    --no-main-window
    --additional-module-paths
      ${CMAKE_BINARY_DIR}/${Slicer_QTSCRIPTEDMODULES_LIB_DIR}
    # The opt-in real-CLI test path calls slicer.cli.run on the scripted PictologicsCLI,
    # which builds into the CLI-modules directory; expose it so
    # slicer.modules.pictologicscli is discoverable.
      ${CMAKE_BINARY_DIR}/${Slicer_CLIMODULES_LIB_DIR}
  )

# The opt-in real CLI path has a 10-minute internal deadline plus bounded
# cancellation and worker-release cleanup. Keep CTest above that bound.
set_tests_properties(
  py_PictologicsSlicerIntegrationTest
  PROPERTIES TIMEOUT 900
  )
