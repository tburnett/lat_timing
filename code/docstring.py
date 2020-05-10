"""Generate documents for IPython display """
import os,inspect,string
import IPython.display as display
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def doc_display(funct, folder_path='figs', fig_kwargs={}, df_kwargs={}, **kwargs):
    """Format and display the docstring, as an alternative to matplotlib inline in jupyter notebooks
    
    Parameters
    ---------
    
    funct : function object
        The calling function, used to obtain the docstring
    folder_path : string, optional, default 'figs'
    fig_kwargs : dict,  optional
        additional kwargs to pass to the savefig call.
    df_kwargs : dict, optional
        additional kwargs to pass to the to_html call for a DataFrame
    kwargs : used only to set variables referenced in the docstring.    
    
    Expect to be called from a function or class method that may generate one or more figures.
    It takes the function's docstring, assumed to be in markdown, and applies format() to format values of any locals. 
    
    Each Figure to be displayed must have a reference in the local namespace, say `fig`, and have a unique number. 
    Then the  figure will be rendered at the position of a '{fig}' entry.
    In addition, if an attribute "caption" is found in a Figure object, its text will be displayed as a caption.
    
    Similarly, if there is a reference to a pandas DataFrame, say a local variable `df`, then any occurrence of `{df}`
    will be replaced with an HTML table.
    
    A possibly important detail, given that The markdown processor expects key symbols, like #, to be the first on a line:
    Docstring text is processed by inspect.cleandoc, which cleans up indentation:
        All leading whitespace is removed from the first line. Any leading whitespace that can be uniformly
        removed from the second line onwards is removed. Empty lines at the beginning and end are subsequently
        removed. Also, all tabs are expanded to spaces.
        
    Finally runs the IPython display to process the markdown for insertion after the code cell that invokes the function.
   
    Unrecognized entries are ignored, allowing latex expressions. (The string must be preceded by an "r"). In case of
    confusion, double the curly brackets.

    """    
    
    # get docstring from function object
    assert inspect.isfunction(funct), f'Expected a function: got {funct}'
    doc = inspect.getdoc(funct)
        
    # use inspect to get caller frame, the function name, and locals dict
    back =inspect.currentframe().f_back
    name= inspect.getframeinfo(back).function
    locs = inspect.getargvalues(back).locals.copy() # since may modify
    # add kwargs if any
    locs.update(kwargs)
    
    # set up path to save figures in folder with function name
    path = f'{folder_path}/{name}'

    
    # process each Figure or DataFrame found in local for display 
    
    class FigureWrapper(plt.Figure):
        def __init__(self, fig):
            self.__dict__.update(fig.__dict__)
            self.fig = fig
            
        @property
        def html(self):
            # backwards compatibility with previous version
            return self.__str__()
            
        def __str__(self):
            if not hasattr(self, '_html'):
                fig=self.fig
                n = fig.number
                caption=getattr(fig,'caption', '').format(**locs)
                # save the figure to a file, then close it
                fig.tight_layout(pad=1.05)
                fn = f'{path}/fig_{n}.png'
                fig.savefig(fn) #, **fig_kwargs)
                plt.close(fig) 

                # add the HTML as an attribute, to insert the image, including optional caption
                self._html =  f'<figure> <img src="{fn}" alt="Figure {n}">'\
                        f' <figcaption>{caption}</figcaption>'\
                        '</figure>'
            return self._html
        
        def __repr__(self):
            return self.__str__()

        
    class DataFrameWrapper(object): #pd.DataFrame):
        def __init__(self, df):
            #self.__dict__.update(df.__dict__) #fails?
            self._df = df
        @property
        def html(self):
            # backwards compatibility with previous version
            return self.__str__()
        def __repr__(self):
            return self.__str__()
        def __str__(self):
            if not hasattr(self, '_html'):
                kwargs = dict(float_format=lambda x: f'{x:.3f}', notebook=True)
                kwargs.update(df_kwargs)
                self._html = self._df.to_html(**kwargs)                
            return self._html

            
    def figure_html(fig):
        if hasattr(fig, 'html'): return
        os.makedirs(path, exist_ok=True)
        
        return FigureWrapper(fig)
        
    def dataframe_html(df):
        if hasattr(df, 'html'): return None
        return DataFrameWrapper(df)
   
    def processor(key, value):
        # value: an object reference to be processed 
        ptable = {plt.Figure: figure_html,
                  pd.DataFrame: dataframe_html,
                 }
        f = ptable.get(value.__class__, lambda x: None)
        # process the reference: if recognized, there may be a new object
        newvalue = f(value)
        if newvalue is not None: 
            locs[key] = newvalue
            #print(f'key={key}, from {value.__class__.__name__} to  {newvalue.__class__.__name__}')
    
    for key,value in locs.items():
        processor(key,value)
   
    # format local references. Process Figure or DataFrame objects found to include .html representations.
    # Use a string.Formatter subclass to ignore bracketed names that are not found
    #adapted from  https://stackoverflow.com/questions/3536303/python-string-format-suppress-silent-keyerror-indexerror

    class Formatter(string.Formatter):
        class Unformatted:
            def __init__(self, key):
                self.key = key
            def format(self, format_spec):
                return "{{{}{}}}".format(self.key, ":" + format_spec if format_spec else "")

        def vformat(self, format_string,  kwargs):
            try:
                return super().vformat(format_string, [], kwargs)
            except AttributeError as msg:
                return f'Failed processing because: {msg.args[0]}'
        def get_value(self, key, args, kwargs):
            return kwargs.get(key, Formatter.Unformatted(key))

        def format_field(self, value, format_spec):
            if isinstance(value, Formatter.Unformatted):
                return value.format(format_spec)
            #print(f'\tformatting {value} with spec {format_spec}') #', object of class {eval(value).__class__}')
            return format(value, format_spec)
                        
    docx = Formatter().vformat(doc+'\n', locs)       
    # replaced: docx = doc.format(**locs)

    # pass to IPython's display as markdown
    display.display(display.Markdown(docx))


def md_display(text):
    """Add text to the display"""
    display.display(display.Markdown(text+'\n'))
    
def demo_function( xlim=(0,10)):
    r"""
    ### Function generating figures and table output

    Note the value of the arg `xlim = {xlim}`

    * Display head of the dataframe used to make the plots
    {dfhead}
    
    * Figure 1.
    Describe analysis for this figure here.
    {fig1}
    Interpret results for Fig. {fig1.number}.  
    
    * Figure 2.
    A second figure!
    {fig2}
    This figure is a sqrt

    ---
    Check value of the kwarg *test* passed to the formatter: it is "{test:.2f}".
    
    ---
    Insert some latex to test that it passes unrecognized entries on.
        \begin{align*}
        \sin(\theta)^2 + \cos(\theta)^2 =1
        \end{align*}
    An inline formula: $\frac{1}{2}=0.5$
    """
    plt.rc('font', size=14)
    x=np.linspace(*xlim)
    df= pd.DataFrame([x,x**2,np.sqrt(x)], index='x xx sqrtx'.split()).T
    dfhead =df.head()
    fig1,ax=plt.subplots(num=1, figsize=(4,4))
    ax.plot(df.x, df.xx)
    ax.set(xlabel='$x$', ylabel='$x^2$', title=f'figure {fig1.number}')
    fig1.caption="""Example caption for Fig. {fig1.number}, which
            shows $x^2$ vs. $x$.    
            <p>A second caption line."""
    
    fig2,ax=plt.subplots(num=2, figsize=(4,4))
    ax.set_title('figure 2')
    ax.plot(df.x, df.sqrtx)
    ax.set(xlabel = '$x$', ylabel=r'$\sqrt{x}$')
        
    
    doc_display(demo_function, test=99)
    