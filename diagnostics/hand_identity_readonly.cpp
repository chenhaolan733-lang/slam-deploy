#include "stark-sdk.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <unistd.h>
int main(int argc, char** argv) {
  if(argc != 4) return 2;
  setbuf(stdout, nullptr);
  const bool fd = strcmp(argv[2], "canfd") == 0;
  const auto protocol = fd ? STARK_PROTOCOL_TYPE_CAN_FD : STARK_PROTOCOL_TYPE_CAN;
  const auto id = static_cast<uint8_t>(atoi(argv[3]));
  if ((fd ? init_socketcan_canfd(argv[1]) : init_socketcan_can(argv[1])) != 0) return 3;
  auto h = init_device_handler_can(protocol, 1, 1000000, fd ? 5000000 : 1000000);
  if (!h) return 4;
  auto d = stark_get_device_info(h, id);
  if(!d) { printf("NO_IDENTITY iface=%s protocol=%s id=%u\n",argv[1],argv[2],id); return 5; }
  printf("IDENTITY iface=%s protocol=%s id=%u hardware_type=%u sku_type=%u serial=%s firmware=%s revo1_motor_api=%d touch=%d\n",argv[1],argv[2],id,(unsigned)d->hardware_type,(unsigned)d->sku_type,d->serial_number,d->firmware_version,device_info_uses_revo1_motor_api(d),device_info_is_touch(d));
  for(int i=0; i<3; ++i) {
    auto s = stark_get_motor_status(h,id);
    if(!s) { puts("STATUS_READ_FAILED"); break; }
    printf("STATUS sample=%d positions=",i);
    for(auto v:s->positions) printf("%u,",v);
    printf(" speeds="); for(auto v:s->speeds) printf("%d,",v);
    printf(" currents="); for(auto v:s->currents) printf("%d,",v);
    printf(" states="); for(auto v:s->states) printf("%u,",v);
    puts(""); free_motor_status_data(s); usleep(100000);
  }
  free_device_info(d); close_device_handler(h,static_cast<uint8_t>(protocol)); close_socketcan();
}
