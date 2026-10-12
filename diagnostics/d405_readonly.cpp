#include <librealsense2/rs.hpp>
#include <iostream>
#include <set>
int main(int argc, char** argv) {
 if (argc != 2) { std::cerr << "Usage: d405_readonly CAMERA_SERIAL\n"; return 2; }
 try {
  rs2::pipeline p; rs2::config c;
  c.enable_device(argv[1]);
  c.enable_stream(RS2_STREAM_DEPTH, 640,480,RS2_FORMAT_Z16,15);
  c.enable_stream(RS2_STREAM_COLOR, 640,480,RS2_FORMAT_RGB8,15);
  auto profile=p.start(c);
  std::set<unsigned long long> depths, colors;
  size_t nonzero=0;
  for(int i=0;i<20;++i) {
   auto f=p.wait_for_frames(3000);
   auto d=f.get_depth_frame(); auto rgb=f.get_color_frame();
   if(!d || !rgb) throw std::runtime_error("Missing depth/color frame");
   depths.insert(d.get_frame_number()); colors.insert(rgb.get_frame_number());
   const auto* data=(const uint16_t*)d.get_data(); nonzero=0;
   for(int j=0;j<d.get_width()*d.get_height();++j) if(data[j]) ++nonzero;
  }
  p.stop();
  std::cout<<"D405 serial="<<argv[1]<<" depth_unique="<<depths.size()<<" color_unique="<<colors.size()<<" last_depth_nonzero="<<nonzero<<"/307200 resolution=640x480 fps=15\n";
  return depths.size()>=15 && colors.size()>=15 && nonzero>0 ? 0:2;
 } catch(const std::exception& e) { std::cerr<<"D405_CHECK_FAILED: "<<e.what()<<"\n"; return 1; }
}
