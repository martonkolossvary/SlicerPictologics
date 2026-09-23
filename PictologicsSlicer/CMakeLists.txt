set(MODULE_NAME PictologicsSlicer)

set(MODULE_PYTHON_SCRIPTS
  ${MODULE_NAME}.py
  PictologicsWidgets/__init__.py
  PictologicsWidgets/results_browser.py
  PictologicsLib/__init__.py
  PictologicsLib/dependency_probe.py
  PictologicsLib/dependencies.py
  PictologicsLib/inline_config.py
  PictologicsLib/jobs.py
  PictologicsLib/progress.py
  PictologicsLib/profiles.py
  PictologicsLib/result_browser.py
  PictologicsLib/results.py
  PictologicsLib/staging.py
  )

set(MODULE_PYTHON_RESOURCES
  Resources/Icons/${MODULE_NAME}.png
  Resources/UI/${MODULE_NAME}.ui
  requirements-pictologics.txt
  )

slicerMacroBuildScriptedModule(
  NAME ${MODULE_NAME}
  SCRIPTS ${MODULE_PYTHON_SCRIPTS}
  RESOURCES ${MODULE_PYTHON_RESOURCES}
  WITH_GENERIC_TESTS
  )

if(BUILD_TESTING)
  add_subdirectory(Testing)
endif()
