from setuptools import find_packages, setup

package_name = 'munder_difflin_control'
setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Andy',
    maintainer_email='andy@munder.difflin',
    description='ROS 2 Executor for the Munder Difflin backend',
    license='Apache-2.0',
    entry_points={'console_scripts': [
        'executor_test = munder_difflin_control.executor_test:main',
        'backend_with_ros = munder_difflin_control.backend_with_ros:run',
    ]},
)
