const copyright = {
  template: `  
   <div class="Mod-copyright">
    <ul class="helpLink">
      <li>关于我们<span class="space"></span></li>
      <li>联系我们<span class="space"></span></li>
      <li>关于我们<span class="space"></span></li>
      <li>商家入驻<span class="space"></span></li>
      <li>营销中心<span class="space"></span></li>
      <li>友情链接<span class="space"></span></li>
      <li>关于我们<span class="space"></span></li>
      <li>营销中心<span class="space"></span></li>
      <li>友情链接<span class="space"></span></li>
      <li>关于我们</li>
    </ul>
    <p>地址：深圳市南山区粤海路 邮编：518060 电话：400-618-9090  网址：https://www.szu.edu.cn </p>
    <p>沪 ICP备xxxxxxxxxx号京公网安备xxxxxxxxxxx</p>
</div>  
    `,
  name: "copyright",
  data() {
    return {}
  }
};
Vue.component("copyright", copyright);