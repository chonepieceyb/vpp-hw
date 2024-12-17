
# Copyright (c) <current-year> <your-organization>
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at:
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

add_vpp_plugin(protocol5
  SOURCES
  protocol5.c
  node.c
  protocol5_periodic.c
  protocol5.h

  MULTIARCH_SOURCES
  node.c

  API_FILES
  protocol5.api

  API_TEST_SOURCES
  protocol5_test.c
)
