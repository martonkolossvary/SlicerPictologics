set(MODULE_NAME PictologicsCLI)

SlicerMacroBuildScriptedCLI(
  NAME ${MODULE_NAME}
  )

if(BUILD_TESTING)
  add_subdirectory(Testing)
endif()
