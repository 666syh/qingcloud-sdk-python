# 主机代入  
1. 在iam主机环境节点上远程登录基础网络ip  
```bash
root@devopsar01n03:~# ssh 10.10.60.2
Welcome to Ubuntu 16.04.4 LTS (GNU/Linux 4.4.0-116-generic x86_64)

 * Documentation:  https://help.ubuntu.com
 * Management:     https://landscape.canonical.com
 * Support:        https://ubuntu.com/advantage

202 packages can be updated.
119 updates are security updates.

``` 

2. 获取安全访问token
```bash
curl -H "Accept: application/json" http://169.254.169.254:80/latest/meta-data/security-credentials
```

3. 开发使用  
    3.1 在根目录新建/opt目录，已有则跳过

    3.2 下载并解压最新sdk文件到/opt
    ```bash
    cd /opt
    wget https://github.com/666syh/qingcloud-sdk-python/archive/1.2.tar.gz
    tar -xf 1.2.tar.gz
    ```

    3.3 编写脚本

    3.3.1 新建脚本文件，起名run

    3.3.2 将 `qingcloud-sdk-python`文件夹 设置进入环境变量
    ```python
    import sys
    sys.path.insert(0, '/opt/qingcloud-sdk-python')
    ```    

    3.3.3 设置api连接（修改对应的host，port及zone，host需要配置 /etc/hosts ）   
    
    ```python
    #API Connection 
    from qingcloud.iaas import APIConnection
    conn=APIConnection(host="api.devopscloud.com",port=80,protocol="http",zone='devops',credential_proxy_host='169.254.169.254',credential_proxy_port=80)
    ```

    3.3.4 应用sdk，sdk详情请参考 [sdk帮助文档](https://docs.qingcloud.com/product/sdk/python/index.html#id3)
    ```python
    ret = conn.describe_routers()# 描述路由器信息
    ```

    3.4 完整实例代码如下
    ```python
    #!/usr/bin/env python

    import sys
    sys.path.insert(0, '/opt/qingcloud-sdk-python')

    #API Connection
    from qingcloud.iaas import APIConnection
    conn=APIConnection(host="api.devopscloud.com",port=80,protocol="http",zone='devops',credential_proxy_host='169.254.169.254',credential_proxy_port=80)

    #Action Test
    print('DescribeRouters: %s' % conn.describe_routers())
    ```

    3.5 注意事项  
    &#160; &#160; &#160; &#160;如果该主机被具有允许访问路由器权限的身份关联，执行上述实例代码后输出结果
    ```bash
    DescribeRouters: {u'action': u'DescribeRoutersResponse', u'router_set': [...], u'ret_code': 0, u'total_count': 1}
    ```
    &#160; &#160; &#160; &#160;如果该主机被具有拒绝访问路由器权限的身份关联，执行上述实例代码后输出结果
    ```bash
    DescribeRouters: {u'message': u'PermissionDenied, IAM authorization evaluate deny', u'ret_code': 1400}
    ```

4. 退出主机代入
    ```bash
    root@i-yitg9rtq:/# logout
    ```
